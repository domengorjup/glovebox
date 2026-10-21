# Stats API

Glovebox has a read-only JSON API under `/api/v1`. The most common use is a Home Assistant REST sensor. A ready-made companion integration with automatic sensors is planned but does not exist yet.

Endpoints and fields: [API reference](../dev/api-reference.md).

## Add-on: enable the API port

Through the sidebar the API is not reachable from outside. To open it:

1. Set `api_token` in the add-on options to a random string of **16 or more characters**. Shorter values stop the add-on with an error.
2. In the add-on **Network** section, set a host port for `8100/tcp` (for example 8100).
3. Restart the add-on.

That port serves only `/api/v1/*`, and only with the header `Authorization: Bearer <token>`. Everything else returns 404. It is plain HTTP, so use it only on a network you trust. If the port is mapped but no token is set, the API does not start and the log says why.

## Standalone

Set `GLOVEBOX_API_TOKEN` (see [Install](install.md)). The API on the normal port then accepts the Bearer header.

## Home Assistant REST sensor

Put the token in `secrets.yaml`, including the word `Bearer`:

```yaml
glovebox_api_header: "Bearer YOUR_TOKEN"
```

Then in `configuration.yaml`. Replace `1` with the vehicle id from `/api/v1/vehicles`. Use the add-on hostname or the Home Assistant IP with the host port:

```yaml
rest:
  - resource: http://homeassistant.local:8100/api/v1/vehicles/1/summary
    scan_interval: 3600
    headers:
      Authorization: !secret glovebox_api_header
    sensor:
      - name: "Car last consumption"
        value_template: "{{ value_json.last_consumption }}"
        unit_of_measurement: "L/100km"
      - name: "Car cost this month"
        value_template: "{{ value_json.cost_this_month }}"
        unit_of_measurement: "EUR"
```

Request the summary URL once (with the header, for example using `curl`) to check the field names before relying on them. See the [REST integration](https://www.home-assistant.io/integrations/rest/) docs for more options.
