## ADDED Requirements

### Requirement: Add-on repository
The project repository SHALL be installable as a Home Assistant add-on repository. It SHALL contain a root `repository.yaml` and an add-on folder with `config.yaml`, `Dockerfile`, `DOCS.md`, `CHANGELOG.md`, `icon.png` and `logo.png`.

#### Scenario: Add repository in HA
- **WHEN** the user adds the repository URL in the HA add-on store
- **THEN** the glovebox add-on is listed and can be installed

### Requirement: Ingress panel
The add-on SHALL enable Ingress, add a sidebar panel titled "Glovebox" with a car icon, and support at least the `amd64` and `aarch64` architectures.

#### Scenario: Open from sidebar
- **WHEN** the installed add-on is started and the user clicks the sidebar panel
- **THEN** the glovebox dashboard opens inside Home Assistant

### Requirement: Persistent data and backups
The add-on SHALL store its SQLite database and settings under `/data`, so that they survive restarts and upgrades and are included in Home Assistant backups. On startup it SHALL apply pending schema migrations automatically.

#### Scenario: Upgrade keeps data
- **WHEN** the add-on is upgraded to a version with a new schema migration
- **THEN** existing records are preserved and the migration is applied at startup

### Requirement: Standalone image from the same build
The same container image SHALL run outside Home Assistant when started in standalone mode. It SHALL listen on port 8080 and store data in a mounted `/data` volume.

#### Scenario: docker run
- **WHEN** a user runs the image with `-p 8080:8080 -v ./data:/data`
- **THEN** the app is reachable at `http://host:8080/`
- **AND** the data persists in `./data`

### Requirement: Optional API port
The add-on `config.yaml` SHALL declare the API port `8100/tcp` under `ports` with the host port `null` (off by default) and describe it under `ports_description`. `ingress_port` SHALL stay `8099`. The `api_token` option SHALL be optional and a password-type field. DOCS.md SHALL explain how to enable the port and the token, and give a Home Assistant `rest:` example with the Bearer header.

#### Scenario: Default install exposes nothing
- **WHEN** the add-on is installed with default settings
- **THEN** no host port is mapped for the API and only Ingress can reach the app

#### Scenario: User enables the API
- **WHEN** the user sets `api_token` (16 characters or more) and a host port for `8100/tcp` in the add-on network settings and restarts
- **THEN** `GET http://<ha-host>:<host-port>/api/v1/vehicles` with the Bearer header returns 200
