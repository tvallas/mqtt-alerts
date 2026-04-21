"""Tests for rule evaluation logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mqtt_alerts.config import ReminderConfig, RuleConfig, SensorConfig
from mqtt_alerts.engine import AlertEngine
from mqtt_alerts.models import ACK_STATUS_ACKNOWLEDGED, ACK_STATUS_ALREADY_ACKNOWLEDGED
from mqtt_alerts.models import RuleKey, RuleState
from mqtt_alerts.persistence import SQLiteStateStore


def test_above_threshold_alerts_after_hold_time() -> None:
    """An above-threshold rule alerts only after the full hold time has elapsed."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 10, 0, 0)

    first = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    second = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=14),
    )
    third = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.3},
        observed_at=start + timedelta(minutes=15),
    )

    assert not first.notifications
    assert not second.notifications
    assert len(third.notifications) == 1
    assert third.notifications[0].rule_id == "high_warn"
    assert "6.30" in third.notifications[0].message
    assert "Threshold: above 5.00" in third.notifications[0].message
    assert "Trigger after: 15m" in third.notifications[0].message
    assert "Exceeded for: 15m" in third.notifications[0].message
    assert "\nCurrent value: 6.30" in third.notifications[0].message


def test_below_threshold_alerts_after_hold_time() -> None:
    """A below-threshold rule uses the same duration behavior."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="low_temp",
                direction="below",
                threshold=-10.0,
                hold_for=timedelta(minutes=5),
                severity="high",
                backend="main_ntfy",
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 11, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": -11.0},
        observed_at=start,
    )
    result = engine.process_message(
        "measurements/freezer1",
        {"temperature": -12.0},
        observed_at=start + timedelta(minutes=5),
    )

    assert len(result.notifications) == 1
    assert result.notifications[0].direction == "below"


def test_one_topic_can_evaluate_multiple_value_fields() -> None:
    """A single MQTT message can update rules for multiple configured sensors."""
    temperature_sensor = _build_sensor()
    battery_sensor = SensorConfig(
        id="freezer_battery",
        name="Freezer battery",
        topic="measurements/freezer1",
        value_field="battery",
        rules=(
            RuleConfig(
                id="low_battery",
                direction="below",
                threshold=2.6,
                hysteresis=0.1,
                hold_for=timedelta(minutes=30),
                severity="critical",
                backend="main_ntfy",
            ),
        ),
    )
    engine = AlertEngine((temperature_sensor, battery_sensor))
    start = _utc(2025, 1, 1, 11, 0, 0)

    assert engine.subscribed_topics() == ["measurements/freezer1"]

    first = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0, "battery": 2.5},
        observed_at=start,
    )
    second = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2, "battery": 2.5},
        observed_at=start + timedelta(minutes=15),
    )
    third = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.3, "battery": 2.5},
        observed_at=start + timedelta(minutes=30),
    )

    assert not first.notifications
    assert [notification.sensor_id for notification in second.notifications] == [
        "freezer_1"
    ]
    assert [notification.sensor_id for notification in third.notifications] == [
        "freezer_battery"
    ]


def test_rule_resets_when_condition_clears_before_hold_time() -> None:
    """The active timer resets if the condition clears before the duration is reached."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 12, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.0},
        observed_at=start + timedelta(minutes=10),
    )
    reset_state = engine.state_for("freezer_1", "high_warn")
    assert reset_state.condition_active is False
    retrigger = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.1},
        observed_at=start + timedelta(minutes=24),
    )
    final = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=39),
    )

    assert not retrigger.notifications
    assert len(final.notifications) == 1


def test_sends_recovery_notification_after_triggered_alert_clears() -> None:
    """A triggered rule emits a recovery notification when values return to normal."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 12, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    triggered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.1},
        observed_at=start + timedelta(minutes=15),
    )
    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.9},
        observed_at=start + timedelta(minutes=16),
    )

    assert len(triggered.notifications) == 1
    assert triggered.notifications[0].kind == "alert"
    assert len(recovered.notifications) == 1
    assert recovered.notifications[0].kind == "recovery"
    assert recovered.notifications[0].title == "Freezer 1 recovered"
    assert "4.90" in recovered.notifications[0].message
    assert "Normal range: below 5.00" in recovered.notifications[0].message
    assert "Exceeded for: 16m" in recovered.notifications[0].message
    assert "\nCurrent value: 4.90" in recovered.notifications[0].message


def test_recovery_notification_can_be_disabled_per_rule() -> None:
    """Rules can opt out of automatic recovery messages."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=15),
                severity="low",
                backend="main_ntfy",
                recovery_enabled=False,
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 12, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.1},
        observed_at=start + timedelta(minutes=15),
    )
    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.9},
        observed_at=start + timedelta(minutes=16),
    )

    assert not recovered.notifications


def test_above_rule_hysteresis_prevents_flapping_recovery() -> None:
    """An active above-threshold rule should not clear until it crosses the hysteresis band."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hysteresis=0.5,
                hold_for=timedelta(minutes=1),
                severity="low",
                backend="main_ntfy",
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 12, 30, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 5.6},
        observed_at=start,
    )
    engine.process_message(
        "measurements/freezer1",
        {"temperature": 5.7},
        observed_at=start + timedelta(minutes=1),
    )
    still_active = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.8},
        observed_at=start + timedelta(minutes=2),
    )
    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.5},
        observed_at=start + timedelta(minutes=3),
    )

    assert not still_active.notifications
    assert engine.state_for("freezer_1", "high_warn").condition_active is False
    assert len(recovered.notifications) == 1
    assert recovered.notifications[0].kind == "recovery"


def test_below_rule_hysteresis_prevents_flapping_recovery() -> None:
    """An active below-threshold rule should not clear until it crosses the hysteresis band."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="low_warn",
                direction="below",
                threshold=-10.0,
                hysteresis=1.0,
                hold_for=timedelta(minutes=1),
                severity="low",
                backend="main_ntfy",
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 12, 45, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": -11.0},
        observed_at=start,
    )
    engine.process_message(
        "measurements/freezer1",
        {"temperature": -11.1},
        observed_at=start + timedelta(minutes=1),
    )
    still_active = engine.process_message(
        "measurements/freezer1",
        {"temperature": -9.5},
        observed_at=start + timedelta(minutes=2),
    )
    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": -9.0},
        observed_at=start + timedelta(minutes=3),
    )

    assert not still_active.notifications
    assert len(recovered.notifications) == 1
    assert recovered.notifications[0].kind == "recovery"


def test_multiple_rules_on_same_sensor_are_independent() -> None:
    """Separate rules on one sensor keep separate timers and trigger independently."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=15),
                severity="low",
                backend="main_ntfy",
            ),
            RuleConfig(
                id="high_critical",
                direction="above",
                threshold=8.0,
                hold_for=timedelta(minutes=10),
                severity="critical",
                backend="main_ntfy",
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 13, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 9.0},
        observed_at=start,
    )
    critical = engine.process_message(
        "measurements/freezer1",
        {"temperature": 9.0},
        observed_at=start + timedelta(minutes=10),
    )
    warning = engine.process_message(
        "measurements/freezer1",
        {"temperature": 9.0},
        observed_at=start + timedelta(minutes=15),
    )

    assert [item.rule_id for item in critical.notifications] == ["high_critical"]
    assert [item.rule_id for item in warning.notifications] == ["high_warn"]


def test_restart_recovery_uses_persisted_active_since(tmp_path) -> None:
    """Persisted rule state lets a restarted process continue the hold timer."""
    sensor = _build_sensor()
    start = _utc(2025, 1, 1, 14, 0, 0)
    key = RuleKey(sensor_id="freezer_1", rule_id="high_warn")
    saved_state = RuleState(
        latest_value=6.0,
        latest_seen_at=start,
        condition_active=True,
        active_since=start,
        alert_triggered=False,
    )
    store = SQLiteStateStore(str(tmp_path / "state.sqlite3"))
    store.save_state(key, saved_state)
    reloaded_engine = AlertEngine((sensor,), initial_state=store.load_states())

    result = reloaded_engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.5},
        observed_at=start + timedelta(minutes=16),
    )

    assert len(result.notifications) == 1
    assert result.notifications[0].rule_id == "high_warn"
    store.close()


def test_persistence_updates_only_when_durable_state_changes() -> None:
    """Fresh readings should not force persistence if the durable state is unchanged."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 15, 0, 0)

    first = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    second = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.1},
        observed_at=start + timedelta(minutes=5),
    )
    third = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=15),
    )
    fourth = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.3},
        observed_at=start + timedelta(minutes=16),
    )

    assert list(first.state_updates) == [
        RuleKey(sensor_id="freezer_1", rule_id="high_warn")
    ]
    assert not second.state_updates
    assert list(third.state_updates) == [
        RuleKey(sensor_id="freezer_1", rule_id="high_warn")
    ]
    assert not fourth.state_updates


def test_custom_messages_include_live_values() -> None:
    """Custom alert and recovery messages should still include the current reading."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=15),
                severity="low",
                backend="main_ntfy",
                message="Custom alert text",
                recovery_message="Recovered with value {value}",
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 15, 30, 0)

    triggered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start,
    )
    triggered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.3},
        observed_at=start + timedelta(minutes=15),
    )
    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.7},
        observed_at=start + timedelta(minutes=16),
    )

    assert (
        triggered.notifications[0].message
        == "Custom alert text\nExceeded for: 15m\nCurrent value: 6.30"
    )
    assert recovered.notifications[0].message == "Recovered with value 4.70"


def test_alert_instance_is_created_when_condition_becomes_active() -> None:
    """Crossing into the active condition should create a pending alert instance."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 16, 0, 0)

    result = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )

    state = engine.state_for("freezer_1", "high_warn")
    assert not result.notifications
    assert state.current_alert is not None
    assert state.current_alert.state == "pending"
    assert state.current_alert.started_at == start


def test_alert_acknowledgement_is_persistent_and_idempotent() -> None:
    """Active alerts should move to acknowledged and duplicate acks should be harmless."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 16, 10, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    fired = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=15),
    )
    alert_id = fired.notifications[0].alert_id

    first = engine.acknowledge_alert(
        alert_id,
        acknowledged_at=start + timedelta(minutes=16),
        acknowledged_by="@alice",
    )
    second = engine.acknowledge_alert(
        alert_id,
        acknowledged_at=start + timedelta(minutes=17),
        acknowledged_by="@alice",
    )

    assert first.status == ACK_STATUS_ACKNOWLEDGED
    assert first.alert is not None
    assert first.alert.state == "acknowledged"
    assert first.alert.acknowledged_by == "@alice"
    assert second.status == ACK_STATUS_ALREADY_ACKNOWLEDGED
    assert engine.state_for("freezer_1", "high_warn").current_alert is not None
    assert (
        engine.state_for("freezer_1", "high_warn").current_alert.state == "acknowledged"
    )


def test_recovery_still_happens_after_acknowledgement() -> None:
    """Acknowledging an alert should not resolve it or suppress the later recovery event."""
    engine = AlertEngine((_build_sensor(),))
    start = _utc(2025, 1, 1, 16, 30, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    fired = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.1},
        observed_at=start + timedelta(minutes=15),
    )
    engine.acknowledge_alert(
        fired.notifications[0].alert_id,
        acknowledged_at=start + timedelta(minutes=16),
        acknowledged_by="@alice",
    )

    recovered = engine.process_message(
        "measurements/freezer1",
        {"temperature": 4.8},
        observed_at=start + timedelta(minutes=17),
    )

    assert len(recovered.notifications) == 1
    assert recovered.notifications[0].kind == "recovery"
    assert recovered.notifications[0].acknowledged_by == "@alice"
    assert engine.state_for("freezer_1", "high_warn").current_alert is None


def test_unacknowledged_alert_sends_reminders_with_backoff() -> None:
    """Unacknowledged firing alerts should emit reminders on the backoff schedule."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=1),
                severity="warning",
                backend="main_telegram",
                reminders=ReminderConfig(
                    enabled=True,
                    initial_delay=timedelta(minutes=5),
                    multiplier=2.0,
                    max_interval=timedelta(hours=1),
                    stop_after=timedelta(hours=24),
                ),
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 17, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    fired = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=1),
    )
    first_early = engine.process_reminders(start + timedelta(minutes=5))
    first_due = engine.process_reminders(start + timedelta(minutes=6))
    second_early = engine.process_reminders(start + timedelta(minutes=15))
    second_due = engine.process_reminders(start + timedelta(minutes=16))

    assert len(fired.notifications) == 1
    assert not first_early.notifications
    assert [item.kind for item in first_due.notifications] == ["reminder"]
    assert first_due.notifications[0].alert_id == fired.notifications[0].alert_id
    assert first_due.notifications[0].title.startswith("Reminder 1:")
    assert not second_early.notifications
    assert [item.kind for item in second_due.notifications] == ["reminder"]
    assert second_due.notifications[0].title.startswith("Reminder 2:")
    assert engine.state_for("freezer_1", "high_warn").reminder_count == 2


def test_acknowledgement_suppresses_reminders() -> None:
    """Acknowledged alerts should remain active but stop reminder delivery."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=1),
                severity="warning",
                backend="main_telegram",
                reminders=ReminderConfig(enabled=True),
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 18, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    fired = engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=1),
    )
    engine.acknowledge_alert(
        fired.notifications[0].alert_id,
        acknowledged_at=start + timedelta(minutes=2),
        acknowledged_by="@alice",
    )
    reminder = engine.process_reminders(start + timedelta(hours=1))

    assert not reminder.notifications


def test_reminders_stop_after_configured_duration() -> None:
    """Reminder delivery should stop after the configured reminder window."""
    sensor = _build_sensor(
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=1),
                severity="warning",
                backend="main_telegram",
                reminders=ReminderConfig(
                    enabled=True,
                    initial_delay=timedelta(minutes=5),
                    stop_after=timedelta(hours=24),
                ),
            ),
        )
    )
    engine = AlertEngine((sensor,))
    start = _utc(2025, 1, 1, 19, 0, 0)

    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.0},
        observed_at=start,
    )
    engine.process_message(
        "measurements/freezer1",
        {"temperature": 6.2},
        observed_at=start + timedelta(minutes=1),
    )
    reminder = engine.process_reminders(start + timedelta(days=1, minutes=1))

    assert not reminder.notifications


def _build_sensor(rules: tuple[RuleConfig, ...] | None = None) -> SensorConfig:
    return SensorConfig(
        id="freezer_1",
        name="Freezer 1",
        topic="measurements/freezer1",
        value_field="temperature",
        rules=rules
        or (
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=5.0,
                hold_for=timedelta(minutes=15),
                severity="low",
                backend="main_ntfy",
            ),
        ),
    )


def _utc(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
