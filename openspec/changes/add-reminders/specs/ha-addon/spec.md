## ADDED Requirements

### Requirement: Home Assistant Core API access
The add-on `config.yaml` SHALL set `homeassistant_api: true`, so that the app can call the Core API through the Supervisor with `SUPERVISOR_TOKEN`. The app SHALL use this access only for the reminders calendar (see reminder-delivery), and SHALL NOT need any new add-on option for it. `DOCS.md` SHALL say what the access is used for.

#### Scenario: Calendars listed in add-on mode
- **WHEN** the add-on runs and HA has a Local Calendar
- **THEN** the Reminders page offers that calendar without any add-on option being set

#### Scenario: Token absent
- **WHEN** the app runs without `SUPERVISOR_TOKEN`
- **THEN** it makes no Core API calls and treats calendar sync as unavailable
