## ADDED Requirements

### Requirement: Serve under a path prefix or at root
The system SHALL generate every link, form action, static-asset URL and API URL relative to a base path. The base path SHALL be taken from the `X-Ingress-Path` request header when present, otherwise from the `BASE_PATH` setting, otherwise `/`.

#### Scenario: Ingress prefix
- **WHEN** a request arrives with `X-Ingress-Path: /api/hassio_ingress/abc123`
- **THEN** all URLs in the returned page start with `/api/hassio_ingress/abc123/`

#### Scenario: Root
- **WHEN** no prefix header or setting is present
- **THEN** all URLs start with `/`

### Requirement: Add-on mode access control
In add-on mode, the system SHALL NOT show a login. It SHALL accept HTTP requests only from the Home Assistant Supervisor ingress proxy, and SHALL reject requests from other source addresses with HTTP 403.

#### Scenario: Direct access rejected
- **WHEN** in add-on mode a request arrives from an address other than the ingress proxy
- **THEN** the response is 403

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
