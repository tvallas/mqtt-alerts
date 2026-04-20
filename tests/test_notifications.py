"""Tests for notification backends."""

from __future__ import annotations

from datetime import datetime, timezone

from mqtt_alerts.config import NtfyBackendConfig
from mqtt_alerts.models import Notification
from mqtt_alerts.notifications import NtfyBackend


def test_ntfy_backend_builds_expected_request() -> None:
    """The ntfy backend maps notification data into an HTTP POST request."""
    captured = {}

    class FakeResponse:
        """Minimal context manager response object."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            """Return a small successful response body."""
            return b"ok"

    def fake_open(request, timeout):
        """Capture the outbound request instead of sending it."""
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    backend = NtfyBackend(
        NtfyBackendConfig(
            id="main_ntfy",
            type="ntfy",
            server="https://ntfy.sh",
            topic="freezer-alerts",
        ),
        opener=fake_open,
    )

    backend.send(
        Notification(
            kind="alert",
            backend_id="main_ntfy",
            sensor_id="freezer_1",
            sensor_name="Freezer 1",
            sensor_topic="measurements/freezer1",
            rule_id="high_critical",
            severity="critical",
            title="Freezer critical alert",
            message="Temperature is too high",
            value=8.6,
            threshold=8.0,
            direction="above",
            occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )

    assert captured["url"] == "https://ntfy.sh/freezer-alerts"
    assert captured["data"] == b"Temperature is too high"
    assert captured["headers"]["Title"] == "Freezer critical alert"
    assert captured["headers"]["Priority"] == "5"
    assert captured["headers"]["Tags"] == "rotating_light"
    assert captured["timeout"] == 10
