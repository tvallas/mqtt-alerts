"""SQLite persistence for per-rule alert state."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from mqtt_alerts.models import ALERT_STATE_FIRING, ALERT_STATE_PENDING, AlertInstance
from mqtt_alerts.models import RuleKey, RuleState


class SQLiteStateStore:
    """Persist rule state plus alert lifecycle instances in local SQLite."""

    def __init__(self, database_path: str) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def load_states(self) -> dict[RuleKey, RuleState]:
        """Load all persisted rule state rows plus any active alert instance."""
        rows = self._connection.execute("""
            SELECT
              rs.sensor_id,
              rs.rule_id,
              rs.latest_value,
              rs.latest_seen_at,
              rs.condition_active,
              rs.active_since,
              rs.alert_triggered,
              rs.triggered_at,
              rs.last_notification_at,
              rs.reminder_count,
              ai.id AS alert_id,
              ai.sensor_name AS alert_sensor_name,
              ai.sensor_topic AS alert_sensor_topic,
              ai.severity AS alert_severity,
              ai.backend_id AS alert_backend_id,
              ai.threshold AS alert_threshold,
              ai.direction AS alert_direction,
              ai.started_at AS alert_started_at,
              ai.state AS alert_state,
              ai.triggered_at AS alert_triggered_at,
              ai.acknowledged_at AS alert_acknowledged_at,
              ai.acknowledged_by AS alert_acknowledged_by,
              ai.resolved_at AS alert_resolved_at
            FROM rule_state rs
            LEFT JOIN alert_instance ai ON ai.id = rs.active_alert_id
            """).fetchall()

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
                reminder_count=row["reminder_count"],
                current_alert=_parse_alert_instance_row(row),
            )
        return states

    def save_state(self, key: RuleKey, state: RuleState) -> None:
        """Persist one state row, including its active alert reference."""
        self.save_updates({key: state}, {})

    def save_updates(
        self,
        state_updates: dict[RuleKey, RuleState],
        alert_updates: dict[str, AlertInstance],
    ) -> None:
        """Persist state and alert updates in one transaction."""
        with self._connection:
            for alert in alert_updates.values():
                self._connection.execute(
                    """
                    INSERT INTO alert_instance (
                      id,
                      sensor_id,
                      sensor_name,
                      sensor_topic,
                      rule_id,
                      severity,
                      backend_id,
                      threshold,
                      direction,
                      started_at,
                      state,
                      triggered_at,
                      acknowledged_at,
                      acknowledged_by,
                      resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      sensor_id = excluded.sensor_id,
                      sensor_name = excluded.sensor_name,
                      sensor_topic = excluded.sensor_topic,
                      rule_id = excluded.rule_id,
                      severity = excluded.severity,
                      backend_id = excluded.backend_id,
                      threshold = excluded.threshold,
                      direction = excluded.direction,
                      started_at = excluded.started_at,
                      state = excluded.state,
                      triggered_at = excluded.triggered_at,
                      acknowledged_at = excluded.acknowledged_at,
                      acknowledged_by = excluded.acknowledged_by,
                      resolved_at = excluded.resolved_at
                    """,
                    (
                        alert.id,
                        alert.sensor_id,
                        alert.sensor_name,
                        alert.sensor_topic,
                        alert.rule_id,
                        alert.severity,
                        alert.backend_id,
                        alert.threshold,
                        alert.direction,
                        _serialize_datetime(alert.started_at),
                        alert.state,
                        _serialize_datetime(alert.triggered_at),
                        _serialize_datetime(alert.acknowledged_at),
                        alert.acknowledged_by,
                        _serialize_datetime(alert.resolved_at),
                    ),
                )

            for key, state in state_updates.items():
                active_alert_id = None
                if state.current_alert is not None:
                    active_alert_id = state.current_alert.id
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
                      last_notification_at,
                      reminder_count,
                      active_alert_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sensor_id, rule_id) DO UPDATE SET
                      latest_value = excluded.latest_value,
                      latest_seen_at = excluded.latest_seen_at,
                      condition_active = excluded.condition_active,
                      active_since = excluded.active_since,
                      alert_triggered = excluded.alert_triggered,
                      triggered_at = excluded.triggered_at,
                      last_notification_at = excluded.last_notification_at,
                      reminder_count = excluded.reminder_count,
                      active_alert_id = excluded.active_alert_id
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
                        state.reminder_count,
                        active_alert_id,
                    ),
                )

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def _initialize_schema(self) -> None:
        self._connection.execute("""
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
              reminder_count INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(sensor_id, rule_id)
            )
            """)
        self._ensure_column("rule_state", "active_alert_id", "TEXT")
        self._ensure_column(
            "rule_state", "reminder_count", "INTEGER NOT NULL DEFAULT 0"
        )
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS alert_instance (
              id TEXT PRIMARY KEY,
              sensor_id TEXT NOT NULL,
              sensor_name TEXT NOT NULL,
              sensor_topic TEXT NOT NULL,
              rule_id TEXT NOT NULL,
              severity TEXT NOT NULL,
              backend_id TEXT NOT NULL,
              threshold REAL NOT NULL,
              direction TEXT NOT NULL,
              started_at TEXT NOT NULL,
              state TEXT NOT NULL,
              triggered_at TEXT,
              acknowledged_at TEXT,
              acknowledged_by TEXT,
              resolved_at TEXT
            )
            """)
        self._backfill_legacy_alert_instances()
        self._connection.commit()

    def _ensure_column(
        self, table_name: str, column_name: str, column_type: str
    ) -> None:
        columns = self._connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        if any(row["name"] == column_name for row in columns):
            return
        self._connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )

    def _backfill_legacy_alert_instances(self) -> None:
        rows = self._connection.execute("""
            SELECT
              sensor_id,
              rule_id,
              latest_value,
              latest_seen_at,
              condition_active,
              active_since,
              alert_triggered,
              triggered_at,
              active_alert_id
            FROM rule_state
            WHERE condition_active = 1 AND active_alert_id IS NULL
            """).fetchall()
        for row in rows:
            started_at = (
                _parse_datetime(row["active_since"])
                or _parse_datetime(row["triggered_at"])
                or _parse_datetime(row["latest_seen_at"])
            )
            if started_at is None:
                continue
            alert_id = uuid5(
                NAMESPACE_URL,
                f"mqtt-alerts:{row['sensor_id']}:{row['rule_id']}:{started_at.isoformat()}",
            ).hex
            state = (
                ALERT_STATE_FIRING if row["alert_triggered"] else ALERT_STATE_PENDING
            )
            self._connection.execute(
                """
                INSERT OR IGNORE INTO alert_instance (
                  id,
                  sensor_id,
                  sensor_name,
                  sensor_topic,
                  rule_id,
                  severity,
                  backend_id,
                  threshold,
                  direction,
                  started_at,
                  state,
                  triggered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    row["sensor_id"],
                    row["sensor_id"],
                    row["sensor_id"],
                    row["rule_id"],
                    "unknown",
                    "legacy",
                    float(row["latest_value"] or 0.0),
                    "above",
                    _serialize_datetime(started_at),
                    state,
                    row["triggered_at"],
                ),
            )
            self._connection.execute(
                """
                UPDATE rule_state
                SET active_alert_id = ?
                WHERE sensor_id = ? AND rule_id = ?
                """,
                (alert_id, row["sensor_id"], row["rule_id"]),
            )


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_alert_instance_row(row: sqlite3.Row) -> AlertInstance | None:
    if row["alert_id"] is None:
        return None
    started_at = _parse_datetime(row["alert_started_at"]) or _parse_datetime(
        row["active_since"]
    )
    if started_at is None:
        return None
    return AlertInstance(
        id=row["alert_id"],
        sensor_id=row["sensor_id"],
        sensor_name=row["alert_sensor_name"],
        sensor_topic=row["alert_sensor_topic"],
        rule_id=row["rule_id"],
        severity=row["alert_severity"],
        backend_id=row["alert_backend_id"],
        threshold=row["alert_threshold"],
        direction=row["alert_direction"],
        started_at=started_at,
        state=row["alert_state"],
        triggered_at=_parse_datetime(row["alert_triggered_at"]),
        acknowledged_at=_parse_datetime(row["alert_acknowledged_at"]),
        acknowledged_by=row["alert_acknowledged_by"],
        resolved_at=_parse_datetime(row["alert_resolved_at"]),
    )
