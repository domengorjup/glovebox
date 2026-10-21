# web-access Specification

## Purpose
TBD - created by archiving change add-autotracker-v1. Update Purpose after archive.
## Requirements
### Requirement: Serve under a path prefix or at root
The system SHALL generate every link, form action, static-asset URL and API URL relative to a base path. The base path SHALL be taken from the `X-Ingress-Path` request header when present, otherwise from the `BASE_PATH` setting, otherwise `/`.

#### Scenario: Ingress prefix
- **WHEN** a request arrives with `X-Ingress-Path: /api/hassio_ingress/abc123`
- **THEN** all URLs in the returned page start with `/api/hassio_ingress/abc123/`

#### Scenario: Root
- **WHEN** no prefix header or setting is present
- **THEN** all URLs start with `/`

### Requirement: Add-on mode access control
In add-on mode, the system SHALL NOT show a login. The Ingress listener SHALL accept HTTP requests only from the Home Assistant Supervisor ingress proxy, and SHALL reject requests from other source addresses with HTTP 403. This SHALL NOT change when the optional API listener is enabled.

#### Scenario: Direct access rejected
- **WHEN** in add-on mode a request arrives from an address other than the ingress proxy
- **THEN** the response is 403

### Requirement: Optional add-on API listener
In add-on mode, the system SHALL run a second listener on the API port (container port 8100) only when `api_token` is set and non-empty. That listener SHALL serve only paths under `/api/v1`, SHALL require `Authorization: Bearer <api_token>`, and SHALL answer every other path with HTTP 404, whether or not a token is sent. It SHALL NOT apply the ingress source-address check. The token SHALL be compared in constant time. A token shorter than 16 characters SHALL make startup fail with an error message naming the minimum length. When `api_token` is not set, the listener SHALL NOT start and the system SHALL log a warning that says how to enable it. Standalone mode SHALL NOT start this listener.

#### Scenario: Token required
- **WHEN** a request to `/api/v1/vehicles` on the API listener has no `Authorization` header
- **THEN** the response is 401 with `WWW-Authenticate: Bearer`

#### Scenario: Wrong token
- **WHEN** a request to `/api/v1/vehicles` on the API listener carries a different Bearer token
- **THEN** the response is 401

#### Scenario: Valid token
- **WHEN** a request to `/api/v1/vehicles` on the API listener carries the configured Bearer token, from any source address
- **THEN** the response is 200 with the same JSON as on the Ingress listener

#### Scenario: Only the API is served
- **WHEN** a request for `/`, `/static/app.css` or `/docs` arrives on the API listener, with or without a valid token
- **THEN** the response is 404

#### Scenario: Ingress listener unchanged
- **WHEN** the API listener is enabled and a request arrives on the Ingress listener from an address other than the ingress proxy
- **THEN** the response is 403
- **AND** a request from the ingress proxy needs no token

#### Scenario: No token, no listener
- **WHEN** the add-on starts without `api_token`
- **THEN** the API listener is not started
- **AND** a warning is logged

#### Scenario: Short token
- **WHEN** the add-on starts with an `api_token` of fewer than 16 characters
- **THEN** startup fails with an error message and no listener starts

#### Scenario: Standalone unchanged
- **WHEN** the app starts in standalone mode with `GLOVEBOX_API_TOKEN` or `GLOVEBOX_PASSWORD` set
- **THEN** only the single listener is started and `/api/v1` is locked behind its Bearer-or-session check

### Requirement: Optional standalone login
In standalone mode, when `GLOVEBOX_PASSWORD` is set, the system SHALL require a login with that password before serving any HTML page, and SHALL keep the session in a signed cookie. When no password is set, the system SHALL serve without login and SHALL log a warning at startup.

#### Scenario: Login required
- **WHEN** a password is configured and an unauthenticated user opens the dashboard
- **THEN** the user is redirected to the login page

#### Scenario: Wrong password
- **WHEN** the user submits a wrong password
- **THEN** access is denied
- **AND** no session cookie is issued

### Requirement: No external network dependencies
Pages SHALL load without internet access. All scripts, styles and fonts SHALL be served by the app itself.

#### Scenario: Offline page load
- **WHEN** the dashboard HTML is rendered
- **THEN** it references no external hosts

