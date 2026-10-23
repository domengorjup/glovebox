"""
Home Assistant Core API client for calendars (design D8), standard library only.

REST (``urllib``) lists calendars and events and creates events. Updating and
deleting events exist only on the websocket API, so a minimal RFC 6455 client
makes one authenticated connection per command. Inside the Supervisor network
there is no TLS, no fragmentation and no long-lived connection to handle.

The calls block; callers run them in a worker thread.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

SUPERVISOR_REST_URL = "http://supervisor/core/api"
SUPERVISOR_WS_URL = "ws://supervisor/core/websocket"
DEFAULT_TIMEOUT = 10.0

# ``supported_features`` bits of a calendar entity.
CREATE_EVENT = 1
DELETE_EVENT = 2
UPDATE_EVENT = 4

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME = 16 * 1024 * 1024


class HaError(Exception):
    """Base class of Home Assistant API failures."""


class HaUnreachable(HaError):
    """No answer: connection refused, timeout or a 5xx answer."""


class HaForbidden(HaError):
    """The token was refused (401/403, or the websocket auth failed)."""


class HaNotFound(HaError):
    """The entity (or the event) does not exist."""


class HaRefused(HaError):
    """Home Assistant understood the request and said no."""


@dataclass(frozen=True)
class CalendarInfo:
    """A calendar entity and what it can do."""

    entity_id: str
    name: str
    features: int

    @property
    def can_create(self) -> bool:
        """The calendar accepts new events."""
        return bool(self.features & CREATE_EVENT)

    @property
    def can_update(self) -> bool:
        """The calendar can change events."""
        return bool(self.features & UPDATE_EVENT)

    @property
    def can_delete(self) -> bool:
        """The calendar can remove events."""
        return bool(self.features & DELETE_EVENT)

    @property
    def capability(self) -> str:
        """Plain words for the calendar choice list."""
        if self.can_update and self.can_delete:
            return "Adds, changes and removes events"
        if self.can_delete:
            return "Adds and removes events"
        if self.can_update:
            return "Adds and changes events"
        return "Only adds events"


@dataclass(frozen=True)
class CalendarEvent:
    """An event as listed by ``GET /calendars/<entity>``."""

    uid: str | None
    summary: str
    description: str
    start: date | None  # None for a timed event


class HaClient:
    """
    Client for the calendar parts of the Home Assistant Core API.

    Parameters
    ----------
    token : str
        Bearer token (``SUPERVISOR_TOKEN`` in an add-on).
    rest_url, ws_url : str
        Base URLs; the defaults are the Supervisor's proxy. Tests point them
        at a local server.
    timeout : float, optional
        Seconds for each connection and read.
    """

    def __init__(
        self,
        token: str,
        rest_url: str = SUPERVISOR_REST_URL,
        ws_url: str = SUPERVISOR_WS_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._token = token
        self._rest_url = rest_url.rstrip("/")
        self._ws_url = ws_url
        self._timeout = timeout

    # --- Calendars and events -------------------------------------------

    def get_calendar(self, entity_id: str) -> CalendarInfo:
        """Name and features of one calendar; ``HaNotFound`` if it is gone."""
        state = self._rest("GET", f"/states/{urllib.parse.quote(entity_id)}")
        attributes = state.get("attributes") or {}
        return CalendarInfo(
            entity_id,
            str(attributes.get("friendly_name") or entity_id),
            int(attributes.get("supported_features") or 0),
        )

    def list_calendars(self) -> list[CalendarInfo]:
        """Every calendar entity that can create events."""
        listed = self._rest("GET", "/calendars")
        calendars = []
        for item in listed if isinstance(listed, list) else []:
            try:
                calendar = self.get_calendar(item["entity_id"])
            except HaNotFound:  # removed between the two calls
                continue
            if calendar.can_create:
                calendars.append(calendar)
        return calendars

    def list_events(self, entity_id: str, start: date, end: date) -> list[CalendarEvent]:
        """Events from ``start`` up to ``end`` (both days included)."""
        query = urllib.parse.urlencode(
            {
                "start": f"{start.isoformat()}T00:00:00Z",
                "end": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            }
        )
        path = f"/calendars/{urllib.parse.quote(entity_id)}?{query}"
        listed = self._rest("GET", path)
        return [_parse_event(item) for item in listed if isinstance(item, dict)]

    def create_event(
        self, entity_id: str, summary: str, description: str, day: date
    ) -> None:
        """Create an all-day event on ``day`` (``calendar.create_event``)."""
        self._rest(
            "POST",
            "/services/calendar/create_event",
            {
                "entity_id": entity_id,
                "summary": summary,
                "description": description,
                "start_date": day.isoformat(),
                "end_date": (day + timedelta(days=1)).isoformat(),
            },
        )

    def update_event(
        self, entity_id: str, uid: str, summary: str, description: str, day: date
    ) -> None:
        """Change an event to an all-day event on ``day`` (websocket)."""
        self._websocket_command(
            {
                "type": "calendar/event/update",
                "entity_id": entity_id,
                "uid": uid,
                "event": {
                    "summary": summary,
                    "description": description,
                    "dtstart": day.isoformat(),
                    "dtend": (day + timedelta(days=1)).isoformat(),
                },
            }
        )

    def delete_event(self, entity_id: str, uid: str) -> None:
        """Remove an event (websocket)."""
        self._websocket_command(
            {"type": "calendar/event/delete", "entity_id": entity_id, "uid": uid}
        )

    # --- REST -------------------------------------------------------------

    def _rest(self, method: str, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._rest_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise _error_for_status(error.code, path) from error
        except (urllib.error.URLError, OSError) as error:
            raise HaUnreachable(f"Home Assistant did not answer: {error}") from error
        try:
            return json.loads(text) if text else None
        except ValueError as error:
            raise HaUnreachable("Home Assistant sent an unreadable answer") from error

    # --- Websocket ----------------------------------------------------------

    def _websocket_command(self, command: dict) -> None:
        """Connect, authenticate, send one command and check its result."""
        try:
            with _WebSocket(self._ws_url, self._timeout) as ws:
                if ws.receive().get("type") != "auth_required":
                    raise HaUnreachable("Unexpected greeting from Home Assistant")
                ws.send({"type": "auth", "access_token": self._token})
                if ws.receive().get("type") != "auth_ok":
                    raise HaForbidden("Home Assistant refused the token")
                ws.send({"id": 1, **command})
                result = _await_result(ws, 1)
        except (OSError, ValueError, _WebSocketClosed) as error:
            raise HaUnreachable(f"Home Assistant did not answer: {error}") from error
        if not result.get("success"):
            raise _error_for_result(result.get("error") or {})


def _error_for_status(status: int, path: str) -> HaError:
    if status in (401, 403):
        return HaForbidden(f"Home Assistant answered {status} for {path}")
    if status == 404:
        return HaNotFound(f"Home Assistant has no {path}")
    if status >= 500:
        return HaUnreachable(f"Home Assistant answered {status} for {path}")
    return HaRefused(f"Home Assistant answered {status} for {path}")


def _error_for_result(error: dict) -> HaError:
    message = str(error.get("message") or "unknown error")
    if error.get("code") in ("not_found", "invalid_entity_id"):
        return HaNotFound(message)
    return HaRefused(message)


def _parse_event(item: dict) -> CalendarEvent:
    start = item.get("start")
    day = None
    if isinstance(start, dict) and start.get("date"):
        day = _parse_date(start["date"])
    elif isinstance(start, str):  # the shape some integrations use
        day = _parse_date(start) if "T" not in start else None
    return CalendarEvent(
        uid=item.get("uid"),
        summary=str(item.get("summary") or ""),
        description=str(item.get("description") or ""),
        start=day,
    )


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


# --- Minimal websocket client --------------------------------------------------


class _WebSocketClosed(Exception):
    """The server closed the connection."""


def _await_result(ws: "_WebSocket", message_id: int) -> dict:
    while True:
        message = ws.receive()
        if message.get("id") == message_id and message.get("type") == "result":
            return message


class _WebSocket:
    """One connection: handshake, masked text frames out, text frames in."""

    def __init__(self, url: str, timeout: float) -> None:
        parts = urllib.parse.urlsplit(url)
        host, port = parts.hostname or "", parts.port or 80
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buffer = b""
        try:
            self._handshake(host, port, parts.path or "/")
        except BaseException:
            self._sock.close()
            raise

    def __enter__(self) -> "_WebSocket":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._sock.close()

    def send(self, message: dict) -> None:
        """Send a JSON message as one masked text frame."""
        payload = json.dumps(message).encode("utf-8")
        size = len(payload)
        if size < 126:
            header = bytes([0x81, 0x80 | size])
        elif size < 65536:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", size)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", size)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def receive(self) -> dict:
        """Read the next JSON text message; pings are answered on the way."""
        while True:
            first, second = self._read(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            if size > _MAX_FRAME:
                raise _WebSocketClosed("frame too large")
            payload = self._read(size)  # server frames are not masked
            opcode = first & 0x0F
            if opcode == 0x8:
                raise _WebSocketClosed("closed by Home Assistant")
            if opcode == 0x9:
                self._sock.sendall(b"\x8a\x80" + os.urandom(4))  # empty pong
            elif opcode == 0x1 and first & 0x80:
                return json.loads(payload.decode("utf-8"))

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self._sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        while b"\r\n\r\n" not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise _WebSocketClosed("closed during the handshake")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise HaUnreachable(f"Websocket upgrade refused: {lines[0]}")
        accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != accept:
            raise HaUnreachable("Websocket handshake answer is wrong")

    def _read(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise _WebSocketClosed("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data


__all__ = [
    "CREATE_EVENT",
    "DELETE_EVENT",
    "UPDATE_EVENT",
    "CalendarEvent",
    "CalendarInfo",
    "HaClient",
    "HaError",
    "HaForbidden",
    "HaNotFound",
    "HaRefused",
    "HaUnreachable",
]
