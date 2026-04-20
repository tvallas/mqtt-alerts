"""Rule evaluation for mqtt-alerts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from mqtt_alerts.config import RuleConfig, SensorConfig
from mqtt_alerts.durations import format_duration
from mqtt_alerts.models import ACK_STATUS_ACKNOWLEDGED, ACK_STATUS_ALREADY_ACKNOWLEDGED
from mqtt_alerts.models import ACK_STATUS_NOT_ACTIVE, ACK_STATUS_NOT_FOUND
from mqtt_alerts.models import ALERT_STATE_ACKNOWLEDGED, ALERT_STATE_FIRING
from mqtt_alerts.models import (
    ALERT_STATE_RESOLVED,
    AcknowledgementResult,
    AlertInstance,
)
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
        self._alert_index: dict[str, RuleKey] = {}
        for key, state in self._state.items():
            if state.current_alert is None:
                continue
            if state.current_alert.state == ALERT_STATE_RESOLVED:
                continue
            self._alert_index[state.current_alert.id] = key

    def subscribed_topics(self) -> list[str]:
        """Return the topics the MQTT client should subscribe to."""
        return sorted(self._sensors_by_topic)

    def process_message(  # pylint: disable=too-many-locals
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
        alert_updates: dict[str, AlertInstance] = {}
        rollback_states: dict[RuleKey, RuleState] = {}

        for rule in sensor.rules:
            if not rule.enabled:
                continue

            key = RuleKey(sensor_id=sensor.id, rule_id=rule.id)
            state = self._state.setdefault(key, RuleState())
            previous_state = state.copy()
            previous_snapshot = previous_state.durable_snapshot()
            notification, alert_update = self._evaluate_rule(
                key,
                sensor,
                rule,
                state,
                value,
                observed_at,
            )
            if state.durable_snapshot() != previous_snapshot:
                state_updates[key] = state.copy()
            if alert_update is not None:
                alert_updates[alert_update.id] = alert_update.copy()
            if notification is not None:
                notifications.append(notification)
                rollback_states[key] = previous_state

        return EvaluationResult(
            notifications=notifications,
            state_updates=state_updates,
            alert_updates=alert_updates,
            rollback_states=rollback_states,
        )

    def state_for(self, sensor_id: str, rule_id: str) -> RuleState:
        """Expose current in-memory state for tests."""
        return self._state[RuleKey(sensor_id=sensor_id, rule_id=rule_id)]

    def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_at: datetime,
        acknowledged_by: str | None,
    ) -> AcknowledgementResult:
        """Acknowledge an active alert instance if it is still firing."""
        key = self._alert_index.get(alert_id)
        if key is None:
            return AcknowledgementResult(status=ACK_STATUS_NOT_FOUND)

        state = self._state[key]
        alert = state.current_alert
        if alert is None or alert.id != alert_id:
            self._alert_index.pop(alert_id, None)
            return AcknowledgementResult(status=ACK_STATUS_NOT_FOUND)

        if alert.state == ALERT_STATE_ACKNOWLEDGED:
            return AcknowledgementResult(
                status=ACK_STATUS_ALREADY_ACKNOWLEDGED,
                alert=alert.copy(),
            )

        if alert.state != ALERT_STATE_FIRING:
            return AcknowledgementResult(
                status=ACK_STATUS_NOT_ACTIVE, alert=alert.copy()
            )

        alert.state = ALERT_STATE_ACKNOWLEDGED
        alert.acknowledged_at = _coerce_utc(acknowledged_at)
        alert.acknowledged_by = acknowledged_by
        updated_state = state.copy()
        updated_alert = alert.copy()
        return AcknowledgementResult(
            status=ACK_STATUS_ACKNOWLEDGED,
            alert=updated_alert,
            state_updates={key: updated_state},
            alert_updates={alert_id: updated_alert},
        )

    def _evaluate_rule(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        key: RuleKey,
        sensor: SensorConfig,
        rule: RuleConfig,
        state: RuleState,
        value: float,
        observed_at: datetime,
    ) -> tuple[Notification | None, AlertInstance | None]:
        state.latest_value = value
        state.latest_seen_at = observed_at

        if _is_condition_active(rule, state, value):
            if not state.condition_active:
                state.condition_active = True
                state.active_since = observed_at
                state.alert_triggered = False
                state.triggered_at = None
                state.last_notification_at = None
                state.current_alert = _create_alert_instance(sensor, rule, observed_at)
                self._alert_index[state.current_alert.id] = key
                return None, state.current_alert.copy()

            if state.active_since is None:
                state.active_since = observed_at
            if state.current_alert is None:
                state.current_alert = _create_alert_instance(
                    sensor, rule, state.active_since
                )
                self._alert_index[state.current_alert.id] = key

            if (
                not state.alert_triggered
                and observed_at - state.active_since >= rule.hold_for
            ):
                alert = state.current_alert
                if alert is None:
                    alert = _create_alert_instance(sensor, rule, state.active_since)
                    state.current_alert = alert
                    self._alert_index[alert.id] = key
                state.alert_triggered = True
                state.triggered_at = observed_at
                state.last_notification_at = observed_at
                alert.state = ALERT_STATE_FIRING
                alert.triggered_at = observed_at
                return (
                    _build_alert_notification(
                        rule,
                        alert,
                        value,
                        observed_at,
                        _active_duration(state.active_since, observed_at),
                    ),
                    alert.copy(),
                )
            return None, None

        should_send_recovery = state.alert_triggered and rule.recovery_enabled
        active_duration = _active_duration(state.active_since, observed_at)
        resolved_alert = None
        if state.current_alert is not None:
            state.current_alert.state = ALERT_STATE_RESOLVED
            state.current_alert.resolved_at = observed_at
            resolved_alert = state.current_alert.copy()
            self._alert_index.pop(state.current_alert.id, None)
        state.condition_active = False
        state.active_since = None
        state.alert_triggered = False
        state.triggered_at = None
        state.last_notification_at = None
        state.current_alert = None
        if should_send_recovery:
            return (
                _build_recovery_notification(
                    resolved_alert,
                    sensor,
                    rule,
                    value,
                    observed_at,
                    active_duration,
                ),
                resolved_alert,
            )
        return None, resolved_alert


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
    rule: RuleConfig,
    alert: AlertInstance,
    value: float,
    observed_at: datetime,
    active_duration: timedelta,
) -> Notification:
    title = rule.title or f"{alert.sensor_name} {alert.severity} alert"
    message = _render_message(
        template=rule.message,
        fallback=(
            f"{alert.sensor_name} alert\n"
            f"Threshold: {alert.direction} {alert.threshold:.2f}\n"
            f"Trigger after: {format_duration(rule.hold_for)}\n"
            f"Exceeded for: {format_duration(active_duration)}\n"
            f"Current value: {value:.2f}"
        ),
        sensor_name=alert.sensor_name,
        threshold=alert.threshold,
        direction=alert.direction,
        severity=alert.severity,
        hold_for=rule.hold_for,
        value=value,
        active_duration=active_duration,
    )
    return Notification(
        kind="alert",
        alert_id=alert.id,
        alert_state=alert.state,
        backend_id=alert.backend_id,
        sensor_id=alert.sensor_id,
        sensor_name=alert.sensor_name,
        sensor_topic=alert.sensor_topic,
        rule_id=alert.rule_id,
        severity=alert.severity,
        title=title,
        message=message,
        value=value,
        threshold=alert.threshold,
        direction=alert.direction,
        occurred_at=observed_at,
    )


def _build_recovery_notification(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    alert: AlertInstance | None,
    sensor: SensorConfig,
    rule: RuleConfig,
    value: float,
    observed_at: datetime,
    active_duration: timedelta,
) -> Notification:
    if alert is None:
        raise ValueError("recovery notification requires a resolved alert instance")
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
        sensor_name=sensor.name,
        threshold=rule.threshold,
        direction=rule.direction,
        severity=rule.severity,
        hold_for=rule.hold_for,
        value=value,
        active_duration=active_duration,
    )
    return Notification(
        kind="recovery",
        alert_id=alert.id,
        alert_state=alert.state,
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
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
    )


def _render_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    template: str | None,
    fallback: str,
    sensor_name: str,
    threshold: float,
    direction: str,
    severity: str,
    hold_for: timedelta | None,
    value: float,
    active_duration: timedelta,
) -> str:
    if template is None:
        return fallback

    if "{" in template and "}" in template:
        return template.format(
            sensor=sensor_name,
            value=f"{value:.2f}",
            threshold=f"{threshold:.2f}",
            direction=direction,
            severity=severity,
            duration=format_duration(hold_for or timedelta()),
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


def _create_alert_instance(
    sensor: SensorConfig,
    rule: RuleConfig,
    started_at: datetime,
) -> AlertInstance:
    return AlertInstance(
        id=uuid4().hex,
        sensor_id=sensor.id,
        sensor_name=sensor.name,
        sensor_topic=sensor.topic,
        rule_id=rule.id,
        severity=rule.severity,
        backend_id=rule.backend,
        threshold=rule.threshold,
        direction=rule.direction,
        started_at=_coerce_utc(started_at),
    )


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
