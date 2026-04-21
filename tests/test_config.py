"""Tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from mqtt_alerts.config import (
    ConfigError,
    NtfyBackendConfig,
    PushoverBackendConfig,
    TelegramBackendConfig,
    load_config,
)


def test_load_config_supports_multiple_rules_and_topic_prefix(tmp_path: Path) -> None:
    """The config loader resolves topics and preserves multiple rules per sensor."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost
  port: 1883
  topic_prefix: measurements

state:
  database: ./state.sqlite3

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: alerts

sensors:
  - id: freezer_1
    name: Freezer 1
    topic: receiver1/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: main_ntfy
        enabled: true
      - id: high_critical
        direction: above
        threshold: 8.0
        for: 10m
        severity: critical
        backend: main_ntfy
        enabled: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.mqtt.host == "localhost"
    assert config.state.database == "./state.sqlite3"
    assert config.sensors[0].topic == "measurements/receiver1/freezer1"
    assert len(config.sensors[0].rules) == 2
    assert isinstance(config.notification_backends[0], NtfyBackendConfig)
    assert config.sensors[0].rules[1].severity == "critical"
    assert config.sensors[0].rules[0].recovery_enabled is True
    assert config.sensors[0].rules[0].hysteresis == 0.0


def test_load_config_supports_multiple_value_fields_on_one_topic(
    tmp_path: Path,
) -> None:
    """One MQTT topic can provide multiple configured value fields."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost
  topic_prefix: measurements

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: alerts

sensors:
  - id: freezer_temperature
    topic: receiver1/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: main_ntfy

  - id: freezer_battery
    topic: receiver1/freezer1
    value_field: battery
    rules:
      - id: low_battery
        direction: below
        threshold: 2.6
        hysteresis: 0.1
        for: 30m
        severity: critical
        backend: main_ntfy
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert [sensor.id for sensor in config.sensors] == [
        "freezer_temperature",
        "freezer_battery",
    ]
    assert config.sensors[0].topic == "measurements/receiver1/freezer1"
    assert config.sensors[1].topic == "measurements/receiver1/freezer1"
    assert config.sensors[0].value_field == "temperature"
    assert config.sensors[1].value_field == "battery"


def test_load_config_rejects_unknown_backend_reference(tmp_path: Path) -> None:
    """Rules must target a known backend id."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: alerts

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: missing_backend
        enabled: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="unknown backend"):
        load_config(config_path)


def test_load_config_supports_rule_hysteresis(tmp_path: Path) -> None:
    """Rules can define a non-negative hysteresis margin."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: alerts

sensors:
  - id: freezer_1
    topic: measurements/freezer1
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
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.sensors[0].rules[0].hysteresis == 0.5


def test_load_config_supports_telegram_backend(tmp_path: Path) -> None:
    """Telegram backend config should parse polling settings and numeric chat ids."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_telegram
      type: telegram
      bot_token: 123456:secret
      chat_id: -100123456
      polling_enabled: true
      polling_timeout_seconds: 3
      polling_interval_seconds: 0.5

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: main_telegram
        enabled: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    backend = config.notification_backends[0]
    assert isinstance(backend, TelegramBackendConfig)
    assert backend.chat_id == "-100123456"
    assert backend.polling_timeout_seconds == 3
    assert backend.polling_interval_seconds == 0.5


def test_load_config_supports_telegram_reminders(tmp_path: Path) -> None:
    """Rules can opt into Telegram reminder delivery with parsed durations."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_telegram
      type: telegram
      bot_token: 123456:secret
      chat_id: -100123456

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: main_telegram
        reminders:
          initial_delay: 3m
          multiplier: 1.5
          max_interval: 30m
          stop_after: 12h
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    reminders = config.sensors[0].rules[0].reminders
    assert reminders.enabled is True
    assert reminders.initial_delay.total_seconds() == 180
    assert reminders.multiplier == 1.5
    assert reminders.max_interval.total_seconds() == 1800
    assert reminders.stop_after.total_seconds() == 43200


def test_load_config_rejects_reminders_for_non_telegram_backend(
    tmp_path: Path,
) -> None:
    """Acknowledgement-driven reminders require Telegram callbacks."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: alerts

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: low
        backend: main_ntfy
        reminders:
          enabled: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="telegram backend"):
        load_config(config_path)


def test_load_config_supports_pushover_backend(tmp_path: Path) -> None:
    """Pushover backend config should parse emergency and polling settings."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_pushover
      type: pushover
      api_token: app-token
      user_key: user-key
      device: iphone
      sound: siren
      url: https://example.test/alerts
      url_title: Alert dashboard
      priority_by_severity:
        low: 0
        warning: 1
        critical: 2
      emergency_retry_seconds: 60
      emergency_expire_seconds: 3600
      polling_enabled: true
      polling_interval_seconds: 15.0

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: critical
        backend: main_pushover
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    backend = config.notification_backends[0]
    assert isinstance(backend, PushoverBackendConfig)
    assert backend.api_token == "app-token"
    assert backend.user_key == "user-key"
    assert backend.device == "iphone"
    assert backend.sound == "siren"
    assert backend.priority_by_severity["critical"] == 2
    assert backend.emergency_retry_seconds == 60
    assert backend.emergency_expire_seconds == 3600
    assert backend.polling_interval_seconds == 15.0


def test_load_config_rejects_invalid_pushover_emergency_retry(
    tmp_path: Path,
) -> None:
    """Pushover emergency retry intervals must satisfy the API minimum."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
mqtt:
  host: localhost

notifications:
  backends:
    - id: main_pushover
      type: pushover
      api_token: app-token
      user_key: user-key
      emergency_retry_seconds: 10

sensors:
  - id: freezer_1
    topic: measurements/freezer1
    value_field: temperature
    rules:
      - id: high_warn
        direction: above
        threshold: 5.0
        for: 15m
        severity: critical
        backend: main_pushover
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="at least 30"):
        load_config(config_path)
