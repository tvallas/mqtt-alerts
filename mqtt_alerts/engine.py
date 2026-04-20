"""Rule evaluation for mqtt-alerts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mqtt_alerts.config import RuleConfig, SensorConfig
from mqtt_alerts.durations import format_duration
from mqtt_alerts.models import EvaluationResult, Notification, RuleKey, RuleState


class AlertEngine:
    """Evaluate sensor payloads against configured rules."""

    def __init__(
        self,
        sensors: tuple[SensorConfig, ...],
        initial_state: dict[RuleKey, RuleState] | None = None,
    ) -> None:
        self._sensors_by_topic = {sensor.topic: sensor for sensor in sensors}
        self._state = dict(initial_state or {})

    def subscribed_topics(self) -> list[str]:
        """Return the topics the MQTT client should subscribe to."""
        return sorted(self._sensors_by_topic)

    def process_message(
        self,
        topic: str,
        payload: dict[str, Any],
        observed_at: datetime,
    ) -> EvaluationResult:
        """Evaluate one MQTT message and return the resulting state updates."""
        sensor = self._sensors_by_topic[topic]
        value = _extract_numeric_value(payload, sensor.value_field)
        notifications: list[Notification] = []
        state_updates: dict[RuleKey, RuleState] = {}

        for rule in sensor.rules:
            if not rule.enabled:
                continue

            key = RuleKey(sensor_id=sensor.id, rule_id=rule.id)
            state = self._state.setdefault(key, RuleState())
            previous_snapshot = state.durable_snapshot()
            notification = self._evaluate_rule(sensor, rule, state, value, observed_at)
            if state.durable_snapshot() != previous_snapshot:
                state_updates[key] = state
            if notification is not None:
                notifications.append(notification)

        return EvaluationResult(notifications=notifications, state_updates=state_updates)

    def state_for(self, sensor_id: str, rule_id: str) -> RuleState:
        """Expose current in-memory state for tests."""
        return self._state[RuleKey(sensor_id=sensor_id, rule_id=rule_id)]

    def _evaluate_rule(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        sensor: SensorConfig,
        rule: RuleConfig,
        state: RuleState,
        value: float,
        observed_at: datetime,
    ) -> Notification | None:
        state.latest_value = value
        state.latest_seen_at = observed_at

        if _is_condition_active(rule, state, value):
            if not state.condition_active:
                state.condition_active = True
                state.active_since = observed_at
                state.alert_triggered = False
                state.triggered_at = None
                state.last_notification_at = None
                return None

            if state.active_since is None:
                state.active_since = observed_at

            if not state.alert_triggered and observed_at - state.active_since >= rule.hold_for:
                state.alert_triggered = True
                state.triggered_at = observed_at
                state.last_notification_at = observed_at
                return _build_alert_notification(
                    sensor,
                    rule,
                    value,
                    observed_at,
                    _active_duration(state.active_since, observed_at),
                )
            return None

        should_send_recovery = state.alert_triggered and rule.recovery_enabled
        active_duration = _active_duration(state.active_since, observed_at)
        state.condition_active = False
        state.active_since = None
        state.alert_triggered = False
        state.triggered_at = None
        state.last_notification_at = None
        if should_send_recovery:
            return _build_recovery_notification(
                sensor,
                rule,
                value,
                observed_at,
                active_duration,
            )
        return None


def _extract_numeric_value(payload: dict[str, Any], field_name: str) -> float:
    raw_value = payload[field_name]
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ValueError(f"payload field {field_name!r} must be numeric")
    return float(raw_value)


def _condition_matches(rule: RuleConfig, value: float) -> bool:
    if rule.direction == "above":
        return value > rule.threshold
    return value < rule.threshold


def _is_condition_active(rule: RuleConfig, state: RuleState, value: float) -> bool:
    if not state.condition_active:
        return _condition_matches(rule, value)

    if rule.direction == "above":
        return value > (rule.threshold - rule.hysteresis)
    return value < (rule.threshold + rule.hysteresis)


def _build_alert_notification(
    sensor: SensorConfig,
    rule: RuleConfig,
    value: float,
    observed_at: datetime,
    active_duration: timedelta,
) -> Notification:
    title = rule.title or f"{sensor.name} {rule.severity} alert"
    message = _render_message(
        template=rule.message,
        fallback=(
            f"{sensor.name} alert\n"
            f"Threshold: {rule.direction} {rule.threshold:.2f}\n"
            f"Trigger after: {format_duration(rule.hold_for)}\n"
            f"Exceeded for: {format_duration(active_duration)}\n"
            f"Current value: {value:.2f}"
        ),
        sensor=sensor,
        rule=rule,
        value=value,
        active_duration=active_duration,
    )
    return Notification(
        kind="alert",
        backend_id=rule.backend,
        sensor_id=sensor.id,
        sensor_name=sensor.name,
        sensor_topic=sensor.topic,
        rule_id=rule.id,
        severity=rule.severity,
        title=title,
        message=message,
        value=value,
        threshold=rule.threshold,
        direction=rule.direction,
        occurred_at=observed_at,
    )


def _build_recovery_notification(
    sensor: SensorConfig,
    rule: RuleConfig,
    value: float,
    observed_at: datetime,
    active_duration: timedelta,
) -> Notification:
    title = rule.recovery_title or f"{sensor.name} recovered"
    normal_direction = "below" if rule.direction == "above" else "above"
    message = _render_message(
        template=rule.recovery_message,
        fallback=(
            f"{sensor.name} recovered\n"
            f"Normal range: {normal_direction} {rule.threshold:.2f}\n"
            f"Exceeded for: {format_duration(active_duration)}\n"
            f"Current value: {value:.2f}"
        ),
        sensor=sensor,
        rule=rule,
        value=value,
        active_duration=active_duration,
    )
    return Notification(
        kind="recovery",
        backend_id=rule.backend,
        sensor_id=sensor.id,
        sensor_name=sensor.name,
        sensor_topic=sensor.topic,
        rule_id=rule.id,
        severity=rule.severity,
        title=title,
        message=message,
        value=value,
        threshold=rule.threshold,
        direction=rule.direction,
        occurred_at=observed_at,
    )


def _render_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    template: str | None,
    fallback: str,
    sensor: SensorConfig,
    rule: RuleConfig,
    value: float,
    active_duration: timedelta,
) -> str:
    if template is None:
        return fallback

    if "{" in template and "}" in template:
        return template.format(
            sensor=sensor.name,
            value=f"{value:.2f}",
            threshold=f"{rule.threshold:.2f}",
            direction=rule.direction,
            severity=rule.severity,
            duration=format_duration(rule.hold_for),
            active_duration=format_duration(active_duration),
        )

    return (
        f"{template}\n"
        f"Exceeded for: {format_duration(active_duration)}\n"
        f"Current value: {value:.2f}"
    )


def _active_duration(active_since: datetime | None, observed_at: datetime) -> timedelta:
    if active_since is None:
        return timedelta()
    return max(observed_at - active_since, timedelta())
