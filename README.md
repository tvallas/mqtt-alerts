# mqtt-alerts

`mqtt-alerts` is a small daemon-style CLI that subscribes to MQTT topics, evaluates alert rules, and sends notifications through pluggable backends.

It exists separately from [`mtr2mqtt`](https://github.com/tvallas/mtr2mqtt) on purpose:

- `mtr2mqtt` publishes measurement data to MQTT.
- `mqtt-alerts` consumes MQTT data and turns sustained threshold violations into persistent alert instances and notifications.

That separation keeps the data publishing path simple while allowing alerting and notification behavior to evolve independently.

## What It Does

- subscribes to configured MQTT topics
- parses JSON payloads and extracts a configured value field
- evaluates multiple independent rules per sensor
- tracks one persistent alert instance per firing period
- models the alert lifecycle as `pending`, `firing`, `acknowledged`, and `resolved`
- persists alert and acknowledgement state in SQLite so restart recovery is correct
- sends notifications through pluggable backends
- sends automatic recovery notifications when triggered rules return to normal
- supports Telegram acknowledgement buttons through outbound long polling only

## What It Does Not Do

This project intentionally stays small. It still does not include:

- arbitrary expressions or a custom rule language
- multiple payload extraction syntaxes
- dashboards or a web UI
- silencing windows or schedules
- repeated reminders or escalation chains
- inbound webhooks or a public HTTP endpoint

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

## Alert Lifecycle And Acknowledgements

Acknowledgement is modeled as a state transition of one alert instance, not as a delivery-side flag.

For each `(sensor_id, rule_id)` pair, `mqtt-alerts` tracks a lifecycle like this:

1. `pending`: the condition is active, but the hold duration has not elapsed yet.
2. `firing`: the hold duration elapsed and an alert notification was sent.
3. `acknowledged`: a human acknowledged the still-active alert instance.
4. `resolved`: the condition cleared.

Important behavior:

- one rule can fire many times over the lifetime of the service
- each firing period gets its own alert instance id
- acknowledgement applies to one active alert instance only
- acknowledgement persists across restart
- acknowledgement does not resolve or clear the alert
- recovery can still be sent after an acknowledged alert later clears

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
    - id: main_telegram
      type: telegram
      bot_token: 123456789:replace-me
      chat_id: -1001234567890
      polling_enabled: true
      polling_timeout_seconds: 1
      polling_interval_seconds: 0.0

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
        severity: warning
        backend: main_telegram
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
- state is tracked per `(sensor_id, rule_id)` pair, while alert instances are tracked separately for each firing period
- Telegram `chat_id` may be a numeric id such as `-100...` for groups

## Notification Backends

The core evaluator emits a generic notification object. Delivery is handled by a backend abstraction so new backends can be added later without redesigning rule evaluation or persistence.

This repository currently ships with:

| Backend | Push notifications | Direct acknowledgement | How interactions arrive | Public internet exposure needed for `mqtt-alerts` | Best fit |
| --- | --- | --- | --- | --- | --- |
| `ntfy` | Yes | No | N/A | No | Outbound notification delivery only |
| `telegram` | Yes | Yes | Bot API `getUpdates` long polling | No | Primary mobile acknowledgement channel |

Practical conclusions:

- `ntfy` is a good outbound notification backend, but it is not the primary interactive acknowledgement channel for this architecture.
- Telegram works well here because `mqtt-alerts` can poll outward to the Telegram Bot API and receive button presses without exposing a webhook endpoint.

## Telegram Setup

### 1. Create a bot and get a token

1. Talk to `@BotFather` in Telegram.
2. Run `/newbot`.
3. Follow the prompts and copy the bot token.

Treat the bot token like a password. Anyone who has it can control the bot.

### 2. Find the chat id

For a direct chat:

1. Start a chat with your bot.
2. Send it any message.
3. Query the Bot API:

```sh
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

4. Look for `message.chat.id` in the JSON response.

For a group:

1. Add the bot to the group.
2. Send a message in the group.
3. Query `getUpdates` the same way.
4. Use the negative group `chat.id`, usually starting with `-100`.

### 3. Configure the backend

```yaml
notifications:
  backends:
    - id: main_telegram
      type: telegram
      bot_token: 123456789:replace-me
      chat_id: -1001234567890
      polling_enabled: true
      polling_timeout_seconds: 1
      polling_interval_seconds: 0.0
```

Field meanings:

- `bot_token`: Telegram bot token from `@BotFather`
- `chat_id`: one target chat for the first version
- `polling_enabled`: disable only if you want outbound Telegram messages without acknowledgements
- `polling_timeout_seconds`: Bot API long-poll timeout; keep this modest because MQTT and Telegram polling share one process loop
- `polling_interval_seconds`: optional delay between polls

### 4. What the Telegram acknowledgement flow looks like

When a rule fires:

1. `mqtt-alerts` sends a Telegram message to the configured chat.
2. The message includes an inline `Acknowledge` button.
3. The callback payload contains a compact alert instance id.

When a user taps the button:

1. `mqtt-alerts` receives the callback through Telegram long polling.
2. The matching active alert instance moves to `acknowledged`.
3. The callback is answered so the Telegram client stops spinning.
4. The Telegram message is updated when practical to show that it was acknowledged.

No inbound webhook and no public HTTP endpoint are required.

## Security Notes

- keep the Telegram bot token out of screenshots, logs, shell history, and public repositories
- keep the config file readable only by the user or service account that runs `mqtt-alerts`
- if the bot is added to a shared group, anyone who can press the acknowledgement button in that chat can acknowledge alerts

## How It Fits With `mtr2mqtt`

A typical setup looks like this:

1. `mtr2mqtt` reads measurements from physical sensors and publishes JSON to MQTT topics.
2. `mqtt-alerts` subscribes to selected measurement topics.
3. `mqtt-alerts` extracts the configured value field and evaluates one or more rules per sensor.
4. When a condition stays active for long enough, `mqtt-alerts` creates or updates an alert instance and sends a notification through the configured backend.
5. If Telegram is configured, acknowledgements flow back through Bot API long polling.

## Architecture

The code is intentionally split into small modules:

- `mqtt_alerts.config`: YAML loading and validation
- `mqtt_alerts.engine`: per-rule threshold evaluation plus alert lifecycle handling
- `mqtt_alerts.persistence`: SQLite rule state and alert instance storage
- `mqtt_alerts.notifications`: backend abstraction plus `ntfy` and Telegram delivery/polling
- `mqtt_alerts.runtime`: MQTT subscription loop and application wiring
- `mqtt_alerts.cli`: CLI entrypoint

SQLite persistence now stores:

- current per-rule evaluation state
- the active alert instance id, when one exists
- alert instance lifecycle timestamps
- acknowledgement metadata such as who acknowledged and when

Existing databases are migrated on startup so in-flight rule state is not lost when upgrading.

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
