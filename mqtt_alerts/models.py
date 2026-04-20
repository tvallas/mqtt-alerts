"""Core runtime data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RuleKey:
    """A stable key for one sensor rule."""

    sensor_id: str
    rule_id: str


@dataclass
class RuleState:
    """Minimum persisted state needed for one rule."""

    latest_value: float | None = None
    latest_seen_at: datetime | None = None
    condition_active: bool = False
    active_since: datetime | None = None
    alert_triggered: bool = False
    triggered_at: datetime | None = None
    last_notification_at: datetime | None = None

    def durable_snapshot(
        self,
    ) -> tuple[bool, datetime | None, bool, datetime | None, datetime | None]:
        """Return only the fields that matter for restart correctness."""
        return (
            self.condition_active,
            self.active_since,
            self.alert_triggered,
            self.triggered_at,
            self.last_notification_at,
        )


@dataclass(frozen=True)
class Notification:  # pylint: disable=too-many-instance-attributes
    """Notification emitted by the alert engine."""

    kind: str
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


@dataclass(frozen=True)
class EvaluationResult:
    """State updates plus any notifications created while processing a message."""

    notifications: list[Notification] = field(default_factory=list)
    state_updates: dict[RuleKey, RuleState] = field(default_factory=dict)
