# mqtt-alerts

`mqtt-alerts` is a small daemon-style CLI that subscribes to MQTT topics, evaluates alert rules, and sends notifications through pluggable backends.

It exists separately from [`mtr2mqtt`](https://github.com/tvallas/mtr2mqtt) on purpose:

- `mtr2mqtt` publishes measurement data to MQTT.
- `mqtt-alerts` consumes MQTT data and turns sustained threshold violations into notifications.

That separation keeps the data publishing path simple while allowing alerting and notification behavior to evolve independently.

## What It Does

- subscribes to configured MQTT topics
- parses JSON payloads and extracts a configured value field
- evaluates multiple independent rules per sensor
- tracks alert timing per rule with a hold duration such as `15m`
- persists minimal per-rule state in SQLite so restart recovery is correct
- sends notifications through pluggable backends
- sends automatic recovery notifications when triggered rules return to normal

## What It Does Not Do

This MVP intentionally does not include:

- arbitrary expressions or a custom rule language
- multiple payload extraction syntaxes
- dashboards or a web UI
- acknowledgements, silencing windows, or schedules
- repeated reminders or escalation chains
- non-`ntfy` notification backends yet

The architecture is prepared for more backends later, but only `ntfy` is implemented in the first release.

## Installation

### Using pip

```sh
pip install mqtt-alerts
```

### Using uv for development

```sh
uv sync --group dev
```

## Basic Usage

Create a config file and run:

```sh
mqtt-alerts --config sample_config.yml
```

CLI flags:

- `--config`, `-c`: path to the YAML configuration file
- `--debug`, `-d`: enable debug logging
- `--quiet`, `-q`: only log warnings and errors
- `--version`, `-v`: print the installed version

Environment variables:

- `MQTT_ALERTS_CONFIG_FILE`
- `MQTT_ALERTS_DEBUG`
- `MQTT_ALERTS_QUIET`

The process polls the config file and applies sensor, rule, backend, and topic changes automatically. Changes to MQTT connection settings or the SQLite database path still require a restart.

## Configuration

The configuration is YAML and keeps MQTT input, persisted state, sensors and rules, and notification backends separate.

```yaml
mqtt:
  host: localhost
  port: 1883
  topic_prefix: measurements

state:
  database: ./mqtt-alerts.sqlite3

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: some-secret-topic

sensors:
  - id: freezer_1
    name: Freezer 1
    topic: receiver1/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        hysteresis: 0.5
        for: 15m
        severity: low
        backend: main_ntfy
        enabled: true
        title: Freezer 1 warning
        message: Temperature is above limit
        recovery_enabled: true
        recovery_title: Freezer 1 recovered
        recovery_message: Temperature is back within range

      - id: high_critical
        direction: above
        threshold: 8.0
        for: 10m
        severity: critical
        backend: main_ntfy
        enabled: true
```

Notes:

- `mqtt.topic_prefix` is optional. If set, sensor topics are resolved under that prefix unless already fully prefixed.
- each sensor can have many rules
- each rule has its own severity, backend, timing, and enabled flag
- each rule can define `hysteresis` to avoid alert/recovery flapping near the threshold
- each rule can customize automatic recovery messages (`recovery_enabled`, `recovery_title`, `recovery_message`)
- state is tracked per `(sensor_id, rule_id)` pair

## Notification Backends

The core evaluator emits a generic notification object. Delivery is handled by a backend abstraction so new backends can be added later without redesigning rule evaluation or persistence.

The MVP ships with one backend:

- `ntfy`

The `ntfy` backend supports:

- server URL
- topic
- title
- message body
- severity mapping to `ntfy` priority and tags

## How It Fits With `mtr2mqtt`

A typical setup looks like this:

1. `mtr2mqtt` reads measurements from physical sensors and publishes JSON to MQTT topics.
2. `mqtt-alerts` subscribes to selected measurement topics.
3. `mqtt-alerts` extracts the configured value field and evaluates one or more rules per sensor.
4. When a condition stays active for long enough, `mqtt-alerts` sends a notification through a configured backend.

## Architecture

The code is intentionally split into small modules:

- `mqtt_alerts.config`: YAML loading and validation
- `mqtt_alerts.engine`: per-rule threshold and duration evaluation
- `mqtt_alerts.persistence`: SQLite state storage
- `mqtt_alerts.notifications`: backend abstraction and `ntfy` delivery
- `mqtt_alerts.runtime`: MQTT subscription loop and application wiring
- `mqtt_alerts.cli`: CLI entrypoint

The persisted state stores only the minimum required fields for restart recovery:

- latest value
- latest timestamp
- whether the condition is active
- when the condition became active
- whether the alert has already triggered
- when the alert triggered
- last notification timestamp

## Docker

Pull the latest image:

```sh
docker pull tvallas/mqtt-alerts:latest
```

Run it with a mounted config:

```sh
docker run --rm \
  -v "$(pwd)/sample_config.yml:/config/config.yml:ro" \
  -v "$(pwd)/state:/state" \
  tvallas/mqtt-alerts:latest \
  --config /config/config.yml
```

There is also a sibling `docker-compose.yml` example in the repository.

## Development

Common commands:

```sh
make install
make lint
make test
make build
```

## Release Flow

The repository mirrors the current `mtr2mqtt` approach:

- pull request CI for lint, tests, and package build
- Docker build smoke test for pull requests
- semantic-release driven GitHub and PyPI release flow
- Docker publish after a successful tagged release
- Dependabot for Python, Docker, and GitHub Actions updates
