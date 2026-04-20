"""SQLite persistence for per-rule alert state."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from mqtt_alerts.models import RuleKey, RuleState


class SQLiteStateStore:
    """Persist minimal rule state in a local SQLite database."""

    def __init__(self, database_path: str) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def load_states(self) -> dict[RuleKey, RuleState]:
        """Load all persisted rule state rows."""
        rows = self._connection.execute(
            """
            SELECT
              sensor_id,
              rule_id,
              latest_value,
              latest_seen_at,
              condition_active,
              active_since,
              alert_triggered,
              triggered_at,
              last_notification_at
            FROM rule_state
            """
        ).fetchall()

        states: dict[RuleKey, RuleState] = {}
        for row in rows:
            key = RuleKey(sensor_id=row["sensor_id"], rule_id=row["rule_id"])
            states[key] = RuleState(
                latest_value=row["latest_value"],
                latest_seen_at=_parse_datetime(row["latest_seen_at"]),
                condition_active=bool(row["condition_active"]),
                active_since=_parse_datetime(row["active_since"]),
                alert_triggered=bool(row["alert_triggered"]),
                triggered_at=_parse_datetime(row["triggered_at"]),
                last_notification_at=_parse_datetime(row["last_notification_at"]),
            )
        return states

    def save_state(self, key: RuleKey, state: RuleState) -> None:
        """Upsert one rule state row."""
        self._connection.execute(
            """
            INSERT INTO rule_state (
              sensor_id,
              rule_id,
              latest_value,
              latest_seen_at,
              condition_active,
              active_since,
              alert_triggered,
              triggered_at,
              last_notification_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sensor_id, rule_id) DO UPDATE SET
              latest_value = excluded.latest_value,
              latest_seen_at = excluded.latest_seen_at,
              condition_active = excluded.condition_active,
              active_since = excluded.active_since,
              alert_triggered = excluded.alert_triggered,
              triggered_at = excluded.triggered_at,
              last_notification_at = excluded.last_notification_at
            """,
            (
                key.sensor_id,
                key.rule_id,
                state.latest_value,
                _serialize_datetime(state.latest_seen_at),
                int(state.condition_active),
                _serialize_datetime(state.active_since),
                int(state.alert_triggered),
                _serialize_datetime(state.triggered_at),
                _serialize_datetime(state.last_notification_at),
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def _initialize_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rule_state (
              sensor_id TEXT NOT NULL,
              rule_id TEXT NOT NULL,
              latest_value REAL,
              latest_seen_at TEXT,
              condition_active INTEGER NOT NULL,
              active_since TEXT,
              alert_triggered INTEGER NOT NULL,
              triggered_at TEXT,
              last_notification_at TEXT,
              PRIMARY KEY(sensor_id, rule_id)
            )
            """
        )
        self._connection.commit()


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
