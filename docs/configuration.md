# Configuration Guide

`mqtt-alerts` reads a single YAML config file describing MQTT input, persistent state, notification backends, and sensors with rules.

## Minimal Shape

```yaml
mqtt:
  host: localhost
  port: 1883
  topic_prefix: measurements

state:
  database: ./mqtt-alerts.sqlite3

notifications:
  backends: []

sensors: []
```

## Full Example

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
      bot_token: "123456789:replace-with-bot-token"
      chat_id: "-1001234567890"
      polling_enabled: true
      polling_timeout_seconds: 1
      polling_interval_seconds: 0.0

    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: replace-with-private-topic

    - id: main_pushover
      type: pushover
      api_token: replace-with-app-token
      user_key: replace-with-user-or-group-key
      sound: siren
      emergency_retry_seconds: 300
      emergency_expire_seconds: 10800
      polling_enabled: true
      polling_interval_seconds: 10.0
      priority_by_severity:
        low: 0
        warning: 1
        high: 1
        critical: 2

sensors:
  - id: freezer_1
    name: Freezer 1
    topic: site-a/freezer-1
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
        title: Freezer warning
        message: Temperature is above limit
        recovery_enabled: true
        recovery_title: Freezer recovered
        recovery_message: Temperature is normal again
        reminders:
          enabled: true
          initial_delay: 5m
          multiplier: 2.0
          max_interval: 1h
          stop_after: 24h
```

## Field Notes

- `mqtt.topic_prefix` is optional. Sensor topics are resolved under this prefix unless already prefixed.
- `state.database` points to the SQLite file for rule and alert lifecycle persistence.
- each sensor can have many rules; each rule can target a different backend.
- `hysteresis` prevents rapid fire/recovery flapping near thresholds.
- `recovery_*` fields customize automatic recovery notifications.
- Telegram reminder settings apply only to rules using a Telegram backend.
