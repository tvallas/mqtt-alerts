"""Tests for SQLite persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from mqtt_alerts.models import AlertInstance, RuleKey, RuleState
from mqtt_alerts.persistence import SQLiteStateStore


def test_acknowledged_alert_persists_across_restart(tmp_path) -> None:
    """Acknowledged alert instances should be restored after reopening the database."""
    database_path = tmp_path / "state.sqlite3"
    key = RuleKey(sensor_id="freezer_1", rule_id="high_warn")
    alert = AlertInstance(
        id="alert-123",
        sensor_id="freezer_1",
        sensor_name="Freezer 1",
        sensor_topic="measurements/freezer1",
        rule_id="high_warn",
        severity="warning",
        backend_id="main_telegram",
        threshold=5.0,
        direction="above",
        started_at=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        state="acknowledged",
        triggered_at=datetime(2025, 1, 1, 10, 15, tzinfo=timezone.utc),
        acknowledged_at=datetime(2025, 1, 1, 10, 16, tzinfo=timezone.utc),
        acknowledged_by="@alice",
    )
    state = RuleState(
        latest_value=6.5,
        latest_seen_at=datetime(2025, 1, 1, 10, 16, tzinfo=timezone.utc),
        condition_active=True,
        active_since=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        alert_triggered=True,
        triggered_at=datetime(2025, 1, 1, 10, 15, tzinfo=timezone.utc),
        last_notification_at=datetime(2025, 1, 1, 10, 15, tzinfo=timezone.utc),
        current_alert=alert,
    )

    store = SQLiteStateStore(str(database_path))
    store.save_updates({key: state}, {alert.id: alert})
    store.close()

    reloaded = SQLiteStateStore(str(database_path))
    loaded_state = reloaded.load_states()[key]

    assert loaded_state.current_alert is not None
    assert loaded_state.current_alert.id == "alert-123"
    assert loaded_state.current_alert.state == "acknowledged"
    assert loaded_state.current_alert.acknowledged_by == "@alice"
    assert loaded_state.condition_active is True
    reloaded.close()
