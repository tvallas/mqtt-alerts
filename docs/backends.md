# Notification Backends

`mqtt-alerts` evaluates rules once and sends notifications through backend adapters.

## Backend Comparison

| Backend | Push notifications | Direct acknowledgement | Interaction path | Public inbound endpoint required |
| --- | --- | --- | --- | --- |
| `ntfy` | Yes | No | N/A | No |
| `telegram` | Yes | Yes | Bot API long polling (`getUpdates`) | No |
| `pushover` | Yes | Yes (emergency receipts) | Receipt polling | No |

## Telegram

```yaml
- id: main_telegram
  type: telegram
  bot_token: "123456789:replace-with-bot-token"
  chat_id: "-1001234567890"
  polling_enabled: true
  polling_timeout_seconds: 1
  polling_interval_seconds: 0.0
```

- Uses outbound long polling, so no webhook hosting is needed.
- Supports acknowledgement buttons linked to active alert instances.
- Supports alert reminders when enabled in rule config.

## ntfy

```yaml
- id: main_ntfy
  type: ntfy
  server: https://ntfy.sh
  topic: replace-with-private-topic
```

- Good for simple outbound delivery.
- Does not provide direct alert acknowledgement in `mqtt-alerts`.

## Pushover

```yaml
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
```

- Emergency priority notifications can repeat until acknowledged in Pushover.
- `mqtt-alerts` stores and polls receipt IDs to map acknowledgement back to alert instances.
