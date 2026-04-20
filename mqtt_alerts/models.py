"""Core runtime data models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

ALERT_STATE_PENDING = "pending"
ALERT_STATE_FIRING = "firing"
ALERT_STATE_ACKNOWLEDGED = "acknowledged"
ALERT_STATE_RESOLVED = "resolved"

ACK_STATUS_ACKNOWLEDGED = "acknowledged"
ACK_STATUS_ALREADY_ACKNOWLEDGED = "already_acknowledged"
ACK_STATUS_NOT_FOUND = "not_found"
ACK_STATUS_NOT_ACTIVE = "not_active"


@dataclass(frozen=True)
class RuleKey:
    """A stable key for one sensor rule."""

    sensor_id: str
    rule_id: str


@dataclass
class RuleState:  # pylint: disable=too-many-instance-attributes
    """Minimum persisted state needed for one rule."""

    latest_value: float | None = None
    latest_seen_at: datetime | None = None
    condition_active: bool = False
    active_since: datetime | None = None
    alert_triggered: bool = False
    triggered_at: datetime | None = None
    last_notification_at: datetime | None = None
    current_alert: "AlertInstance | None" = None

    def durable_snapshot(
        self,
    ) -> tuple[
        bool,
        datetime | None,
        bool,
        datetime | None,
        datetime | None,
        tuple[
            str,
            str,
            datetime,
            datetime | None,
            datetime | None,
            str | None,
            datetime | None,
        ]
        | None,
    ]:
        """Return only the fields that matter for restart correctness."""
        return (
            self.condition_active,
            self.active_since,
            self.alert_triggered,
            self.triggered_at,
            self.last_notification_at,
            (
                None
                if self.current_alert is None
                else self.current_alert.durable_snapshot()
            ),
        )

    def copy(self) -> "RuleState":
        """Return a detached copy suitable for rollback snapshots."""
        return replace(
            self,
            current_alert=(
                None if self.current_alert is None else self.current_alert.copy()
            ),
        )


@dataclass
class AlertInstance:  # pylint: disable=too-many-instance-attributes
    """One alert lifecycle instance for a specific sensor/rule pair."""

    id: str
    sensor_id: str
    sensor_name: str
    sensor_topic: str
    rule_id: str
    severity: str
    backend_id: str
    threshold: float
    direction: str
    started_at: datetime
    state: str = ALERT_STATE_PENDING
    triggered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None

    def durable_snapshot(
        self,
    ) -> tuple[
        str,
        str,
        datetime,
        datetime | None,
        datetime | None,
        str | None,
        datetime | None,
    ]:
        """Return the persisted fields used for restart correctness."""
        return (
            self.id,
            self.state,
            self.started_at,
            self.triggered_at,
            self.acknowledged_at,
            self.acknowledged_by,
            self.resolved_at,
        )

    def copy(self) -> "AlertInstance":
        """Return a detached copy suitable for persistence updates."""
        return replace(self)


@dataclass(frozen=True)
class Notification:  # pylint: disable=too-many-instance-attributes
    """Notification emitted by the alert engine."""

    kind: str
    alert_id: str
    alert_state: str
    backend_id: str
    sensor_id: str
    sensor_name: str
    sensor_topic: str
    rule_id: str
    severity: str
    title: str
    message: str
    value: float
    threshold: float
    direction: str
    occurred_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    """State updates plus any notifications created while processing a message."""

    notifications: list[Notification] = field(default_factory=list)
    state_updates: dict[RuleKey, RuleState] = field(default_factory=dict)
    alert_updates: dict[str, AlertInstance] = field(default_factory=dict)
    rollback_states: dict[RuleKey, RuleState] = field(default_factory=dict)


@dataclass(frozen=True)
class AcknowledgementResult:
    """Result of acknowledging an active alert instance."""

    status: str
    alert: AlertInstance | None = None
    state_updates: dict[RuleKey, RuleState] = field(default_factory=dict)
    alert_updates: dict[str, AlertInstance] = field(default_factory=dict)
