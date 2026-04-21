# Examples

These examples show common deployment patterns for this general-purpose MQTT alerting service.

## Example 1: Freezer Monitoring

```yaml
sensors:
  - id: freezer_a
    name: Freezer A
    topic: plant1/freezer/a
    value_field: temperature
    rules:
      - id: warn_high
        direction: above
        threshold: -10.0
        hysteresis: 1.0
        for: 30m
        severity: warning
        backend: main_telegram
        enabled: true
        title: Freezer A warning
        message: Freezer A temperature is above -10 C
```

## Example 2: Room Humidity

```yaml
sensors:
  - id: room_humidity
    name: Warehouse humidity
    topic: environment/warehouse/humidity
    value_field: humidity
    rules:
      - id: humidity_high
        direction: above
        threshold: 75
        hysteresis: 3
        for: 10m
        severity: high
        backend: main_ntfy
        enabled: true
        title: Humidity high
        message: Humidity has exceeded 75 percent
```

## Example 3: Battery Voltage Drop

```yaml
sensors:
  - id: battery_bank_1
    name: Battery bank 1
    topic: power/battery/bank1
    value_field: voltage
    rules:
      - id: voltage_low_critical
        direction: below
        threshold: 46.5
        hysteresis: 0.4
        for: 3m
        severity: critical
        backend: main_pushover
        enabled: true
        title: Battery voltage critical
        message: Battery bank 1 voltage is below safe threshold
```

## Example 4: Pairing With `mtr2mqtt`

If you already use `mtr2mqtt`, keep it as the data publisher and let `mqtt-alerts` handle alerting:

1. `mtr2mqtt` publishes sensor readings as JSON to MQTT.
2. `mqtt-alerts` subscribes to the configured topics.
3. Rules evaluate values and send notifications when conditions persist.

This is only one integration pattern. `mqtt-alerts` is producer-agnostic as long as payload shape matches your `value_field`.
