"""Tests for rule evaluation logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mqtt_alerts.config import RuleConfig, SensorConfig
from mqtt_alerts.engine import AlertEngine
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
    assert "Duration: 15m" in third.notifications[0].message
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

    assert list(first.state_updates) == [RuleKey(sensor_id="freezer_1", rule_id="high_warn")]
    assert not second.state_updates
    assert list(third.state_updates) == [RuleKey(sensor_id="freezer_1", rule_id="high_warn")]
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

    assert triggered.notifications[0].message == "Custom alert text\nCurrent value: 6.30."
    assert recovered.notifications[0].message == "Recovered with value 4.70"


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
