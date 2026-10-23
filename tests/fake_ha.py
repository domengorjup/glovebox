"""
A small fake Home Assistant for tests: REST and websocket on one local port.

It implements just what ``glovebox.services.ha_calendar`` calls: the calendar
list and states, event listing, ``calendar.create_event`` and the websocket
commands ``calendar/event/update`` and ``calendar/event/delete``. Behaviour
switches (``status``, ``delay_listing``, ``ws_auth_ok``) let tests produce
failures without patching anything in the code under test.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

TOKEN = "test-token"
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass
class FakeCalendar:
    """A calendar entity: name, ``supported_features`` and its events."""

    name: str
    features: int = 7
    events: list[dict] = field(default_factory=list)


class FakeHa:
    """Run with ``with FakeHa() as ha:``; point a client at ``ha.rest_url``."""

    def __init__(self) -> None:
        self.calendars: dict[str, FakeCalendar] = {}
        self.status: int | None = None  # answer every REST call with this status
        self.delay_listing = 0  # created events show up after this many listings
        self.ws_auth_ok = True
        self.calls: list[tuple[str, str]] = []
        self._pending: list[tuple[int, str, dict]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )

    @property
    def rest_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/core/api"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self._server.server_port}/core/websocket"

    def add_calendar(self, entity_id: str, name: str, features: int = 7) -> FakeCalendar:
        self.calendars[entity_id] = FakeCalendar(name, features)
        return self.calendars[entity_id]

    def events(self, entity_id: str) -> list[dict]:
        return self.calendars[entity_id].events

    def __enter__(self) -> "FakeHa":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    # --- Behaviour -------------------------------------------------------------

    def create(self, entity_id: str, body: dict) -> None:
        event = {
            "uid": str(uuid.uuid4()),
            "summary": body["summary"],
            "description": body.get("description", ""),
            "start": {"date": body["start_date"]},
            "end": {"date": body["end_date"]},
        }
        if self.delay_listing:
            self._pending.append((self.delay_listing, entity_id, event))
        else:
            self.calendars[entity_id].events.append(event)

    def listing(self, entity_id: str) -> list[dict]:
        still_waiting = []
        for remaining, entity, event in self._pending:
            if remaining <= 1:
                self.calendars[entity].events.append(event)
            else:
                still_waiting.append((remaining - 1, entity, event))
        self._pending = still_waiting
        return list(self.calendars[entity_id].events)


def _make_handler(ha: FakeHa) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:
            pass

        # --- REST ---------------------------------------------------------------

        def _send(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {TOKEN}"

        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Upgrade", "").lower() == "websocket":
                self._websocket()
                return
            parts = urlsplit(self.path)
            ha.calls.append(("GET", parts.path))
            if ha.status is not None:
                self._send(ha.status, {"message": "forced"})
            elif not self._authorised():
                self._send(401, {"message": "unauthorized"})
            else:
                self._route_get(parts)

        def _route_get(self, parts) -> None:  # noqa: ANN001
            path = parts.path.removeprefix("/core/api")
            if path == "/calendars":
                self._send(200, [{"entity_id": e, "name": c.name}
                                 for e, c in ha.calendars.items()])
            elif path.startswith("/states/"):
                entity = unquote(path.removeprefix("/states/"))
                calendar = ha.calendars.get(entity)
                if calendar is None:
                    self._send(404, {"message": "Entity not found."})
                else:
                    self._send(200, {"entity_id": entity, "state": "off", "attributes": {
                        "friendly_name": calendar.name,
                        "supported_features": calendar.features}})
            elif path.startswith("/calendars/"):
                entity = unquote(path.removeprefix("/calendars/"))
                if entity not in ha.calendars:
                    self._send(404, {"message": "Entity not found."})
                else:
                    assert {"start", "end"} <= set(parse_qs(parts.query))
                    self._send(200, ha.listing(entity))
            else:
                self._send(404, {"message": "unknown"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            path = urlsplit(self.path).path
            ha.calls.append(("POST", path))
            if ha.status is not None:
                self._send(ha.status, {"message": "forced"})
            elif not self._authorised():
                self._send(401, {"message": "unauthorized"})
            elif path == "/core/api/services/calendar/create_event":
                if body["entity_id"] not in ha.calendars:
                    self._send(404, {"message": "Entity not found."})
                else:
                    ha.create(body["entity_id"], body)
                    self._send(200, [])
            else:
                self._send(404, {"message": "unknown"})

        # --- Websocket ------------------------------------------------------------

        def _websocket(self) -> None:
            key = self.headers["Sec-WebSocket-Key"]
            accept = base64.b64encode(
                hashlib.sha1((key + _GUID).encode()).digest()).decode()
            self.wfile.write(
                ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
            self.wfile.flush()
            self.close_connection = True
            self._ws_send({"type": "auth_required"})
            auth = self._ws_receive()
            ok = ha.ws_auth_ok and auth.get("access_token") == TOKEN
            self._ws_send({"type": "auth_ok" if ok else "auth_invalid"})
            if not ok:
                return
            command = self._ws_receive()
            ha.calls.append(("WS", command["type"]))
            self._ws_send(self._ws_result(command))

        def _ws_result(self, command: dict) -> dict:
            answer = {"id": command["id"], "type": "result", "success": True, "result": None}
            calendar = ha.calendars.get(command["entity_id"])
            if calendar is None:
                return answer | {"success": False,
                                 "error": {"code": "not_found", "message": "no such entity"}}
            wanted = next((e for e in calendar.events if e["uid"] == command["uid"]), None)
            if wanted is None:
                return answer | {"success": False,
                                 "error": {"code": "home_assistant_error",
                                           "message": "event not found"}}
            if command["type"].endswith("delete"):
                calendar.events.remove(wanted)
            else:
                event = command["event"]
                wanted.update(summary=event["summary"], description=event["description"],
                              start={"date": event["dtstart"]}, end={"date": event["dtend"]})
            return answer

        def _ws_send(self, message: dict) -> None:
            payload = json.dumps(message).encode()
            if len(payload) < 126:
                header = bytes([0x81, len(payload)])
            else:
                header = bytes([0x81, 126]) + struct.pack(">H", len(payload))
            self.wfile.write(header + payload)
            self.wfile.flush()

        def _ws_receive(self) -> dict:
            first, second = self.rfile.read(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self.rfile.read(2))[0]
            mask = self.rfile.read(4)
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(self.rfile.read(size)))
            assert first == 0x81 and second & 0x80  # one masked text frame
            return json.loads(data)

    return Handler
