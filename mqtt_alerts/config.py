"""Configuration loading and validation for mqtt-alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from mqtt_alerts.durations import parse_duration


class ConfigError(Exception):
    """Raised when the YAML configuration is invalid."""


@dataclass(frozen=True)
class MqttConfig:
    """MQTT connection settings."""

    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    keepalive: int = 60
    client_id: str | None = None
    topic_prefix: str | None = None


@dataclass(frozen=True)
class StateConfig:
    """Persistence settings."""

    database: str


@dataclass(frozen=True)
class NotificationBackendConfig:
    """Base notification backend configuration."""

    id: str
    type: str


@dataclass(frozen=True)
class NtfyBackendConfig(NotificationBackendConfig):
    """Configuration for the ntfy backend."""

    server: str
    topic: str


@dataclass(frozen=True)
class RuleConfig:  # pylint: disable=too-many-instance-attributes
    """One alert rule attached to a sensor."""

    id: str
    direction: str
    threshold: float
    hold_for: timedelta
    severity: str
    backend: str
    enabled: bool = True
    title: str | None = None
    message: str | None = None
    recovery_enabled: bool = True
    recovery_title: str | None = None
    recovery_message: str | None = None


@dataclass(frozen=True)
class SensorConfig:
    """A sensor topic plus its configured alert rules."""

    id: str
    name: str
    topic: str
    value_field: str
    rules: tuple[RuleConfig, ...]


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""

    mqtt: MqttConfig
    state: StateConfig
    notification_backends: tuple[NotificationBackendConfig, ...]
    sensors: tuple[SensorConfig, ...]


def load_config(path: str | Path) -> AppConfig:
    """Load and validate the YAML configuration file."""
    config_path = Path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"failed to read config file {config_path}: {error}") from error

    try:
        payload = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as error:
        raise ConfigError(f"failed to parse YAML in {config_path}: {error}") from error

    data = _require_mapping(payload, "config")
    mqtt = _load_mqtt_config(data.get("mqtt"))
    state = _load_state_config(data.get("state"))
    backends = _load_notification_backends(data.get("notifications"))
    sensors = _load_sensors(data.get("sensors"), mqtt.topic_prefix)

    backend_ids = {backend.id for backend in backends}
    for sensor in sensors:
        for rule in sensor.rules:
            if rule.backend not in backend_ids:
                raise ConfigError(
                    f"sensor {sensor.id!r} rule {rule.id!r} references unknown backend "
                    f"{rule.backend!r}"
                )

    return AppConfig(
        mqtt=mqtt,
        state=state,
        notification_backends=tuple(backends),
        sensors=tuple(sensors),
    )


def _load_mqtt_config(raw_value: Any) -> MqttConfig:
    data = _require_mapping(raw_value, "mqtt")
    return MqttConfig(
        host=_require_string(data.get("host"), "mqtt.host"),
        port=_coerce_int(data.get("port", 1883), "mqtt.port"),
        username=_optional_string(data.get("username"), "mqtt.username"),
        password=_optional_string(data.get("password"), "mqtt.password"),
        keepalive=_coerce_int(data.get("keepalive", 60), "mqtt.keepalive"),
        client_id=_optional_string(data.get("client_id"), "mqtt.client_id"),
        topic_prefix=_normalize_optional_topic_prefix(data.get("topic_prefix")),
    )


def _load_state_config(raw_value: Any) -> StateConfig:
    data = _require_mapping(raw_value or {}, "state")
    database = _optional_string(data.get("database"), "state.database")
    return StateConfig(database=database or "mqtt-alerts.sqlite3")


def _load_notification_backends(raw_value: Any) -> list[NotificationBackendConfig]:
    data = _require_mapping(raw_value, "notifications")
    raw_backends = data.get("backends")
    if not isinstance(raw_backends, list) or not raw_backends:
        raise ConfigError("notifications.backends must be a non-empty list")

    backends: list[NotificationBackendConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_backends):
        entry = _require_mapping(item, f"notifications.backends[{index}]")
        backend_id = _require_string(entry.get("id"), f"notifications.backends[{index}].id")
        if backend_id in seen_ids:
            raise ConfigError(f"duplicate notification backend id {backend_id!r}")
        seen_ids.add(backend_id)

        backend_type = _require_string(
            entry.get("type"), f"notifications.backends[{index}].type"
        )
        if backend_type != "ntfy":
            raise ConfigError(
                f"unsupported backend type {backend_type!r}; only 'ntfy' is implemented"
            )

        backends.append(
            NtfyBackendConfig(
                id=backend_id,
                type=backend_type,
                server=_require_string(
                    entry.get("server"), f"notifications.backends[{index}].server"
                ),
                topic=_require_string(
                    entry.get("topic"), f"notifications.backends[{index}].topic"
                ),
            )
        )
    return backends


def _load_sensors(raw_value: Any, topic_prefix: str | None) -> list[SensorConfig]:
    if not isinstance(raw_value, list) or not raw_value:
        raise ConfigError("sensors must be a non-empty list")

    sensors: list[SensorConfig] = []
    seen_sensor_ids: set[str] = set()
    resolved_topics: set[str] = set()
    for index, item in enumerate(raw_value):
        entry = _require_mapping(item, f"sensors[{index}]")
        sensor_id = _require_string(entry.get("id"), f"sensors[{index}].id")
        if sensor_id in seen_sensor_ids:
            raise ConfigError(f"duplicate sensor id {sensor_id!r}")
        seen_sensor_ids.add(sensor_id)

        resolved_topic = _resolve_topic(
            topic_prefix,
            _require_string(entry.get("topic"), f"sensors[{index}].topic"),
        )
        if resolved_topic in resolved_topics:
            raise ConfigError(f"duplicate sensor topic {resolved_topic!r}")
        resolved_topics.add(resolved_topic)

        rules = _load_rules(sensor_id, entry.get("rules"))
        sensors.append(
            SensorConfig(
                id=sensor_id,
                name=_optional_string(entry.get("name"), f"sensors[{index}].name")
                or sensor_id,
                topic=resolved_topic,
                value_field=_require_string(
                    entry.get("value_field"), f"sensors[{index}].value_field"
                ),
                rules=tuple(rules),
            )
        )
    return sensors


def _load_rules(sensor_id: str, raw_value: Any) -> list[RuleConfig]:
    if not isinstance(raw_value, list) or not raw_value:
        raise ConfigError(f"sensor {sensor_id!r} must define a non-empty rules list")

    rules: list[RuleConfig] = []
    seen_rule_ids: set[str] = set()
    for index, item in enumerate(raw_value):
        entry = _require_mapping(item, f"sensor {sensor_id} rules[{index}]")
        rule_id = _require_string(entry.get("id"), f"sensor {sensor_id} rules[{index}].id")
        if rule_id in seen_rule_ids:
            raise ConfigError(f"duplicate rule id {rule_id!r} for sensor {sensor_id!r}")
        seen_rule_ids.add(rule_id)

        direction = _require_string(
            entry.get("direction"), f"sensor {sensor_id} rules[{index}].direction"
        )
        if direction not in {"above", "below"}:
            raise ConfigError(
                f"sensor {sensor_id!r} rule {rule_id!r} has invalid direction "
                f"{direction!r}; expected 'above' or 'below'"
            )

        raw_duration = entry.get("for", entry.get("duration"))
        if raw_duration is None:
            raise ConfigError(
                f"sensor {sensor_id!r} rule {rule_id!r} must define 'for' duration"
            )

        try:
            hold_for = parse_duration(_require_string(raw_duration, "rule duration"))
        except ValueError as error:
            raise ConfigError(
                f"sensor {sensor_id!r} rule {rule_id!r} has invalid duration: {error}"
            ) from error

        rules.append(
            RuleConfig(
                id=rule_id,
                direction=direction,
                threshold=_coerce_float(
                    entry.get("threshold"), f"sensor {sensor_id} rules[{index}].threshold"
                ),
                hold_for=hold_for,
                severity=_require_string(
                    entry.get("severity"), f"sensor {sensor_id} rules[{index}].severity"
                ),
                backend=_require_string(
                    entry.get("backend"), f"sensor {sensor_id} rules[{index}].backend"
                ),
                enabled=_coerce_bool(
                    entry.get("enabled", True), f"sensor {sensor_id} rules[{index}].enabled"
                ),
                title=_optional_string(
                    entry.get("title"), f"sensor {sensor_id} rules[{index}].title"
                ),
                message=_optional_string(
                    entry.get("message"), f"sensor {sensor_id} rules[{index}].message"
                ),
                recovery_enabled=_coerce_bool(
                    entry.get("recovery_enabled", True),
                    f"sensor {sensor_id} rules[{index}].recovery_enabled",
                ),
                recovery_title=_optional_string(
                    entry.get("recovery_title"),
                    f"sensor {sensor_id} rules[{index}].recovery_title",
                ),
                recovery_message=_optional_string(
                    entry.get("recovery_message"),
                    f"sensor {sensor_id} rules[{index}].recovery_message",
                ),
            )
        )
    return rules


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field_name} must be a mapping")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _coerce_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer")
    return value


def _coerce_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} must be numeric")
    return float(value)


def _coerce_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field_name} must be a boolean")
    return value


def _normalize_optional_topic_prefix(value: Any) -> str | None:
    if value is None:
        return None
    prefix = _require_string(value, "mqtt.topic_prefix").strip("/")
    return prefix or None


def _resolve_topic(topic_prefix: str | None, topic: str) -> str:
    normalized_topic = topic.strip("/")
    if topic_prefix is None:
        return normalized_topic
    if normalized_topic == topic_prefix or normalized_topic.startswith(f"{topic_prefix}/"):
        return normalized_topic
    return f"{topic_prefix}/{normalized_topic}"
