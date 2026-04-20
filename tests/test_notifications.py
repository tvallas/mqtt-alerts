"""Tests for notification backends."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from mqtt_alerts.config import NtfyBackendConfig, TelegramBackendConfig
from mqtt_alerts.models import (
    ACK_STATUS_ACKNOWLEDGED,
    AcknowledgementResult,
    AlertInstance,
)
from mqtt_alerts.models import Notification
from mqtt_alerts.notifications import NtfyBackend, TelegramBackend
from mqtt_alerts.notifications import TelegramInteraction, build_telegram_callback_data
from mqtt_alerts.notifications import parse_telegram_callback_data


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
            alert_id="alert-1",
            alert_state="firing",
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


def test_telegram_backend_builds_alert_message_with_ack_button() -> None:
    """Telegram alert delivery should include the configured chat and ack callback."""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 42}}).encode(
                "utf-8"
            )

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    backend = TelegramBackend(
        TelegramBackendConfig(
            id="main_telegram",
            type="telegram",
            bot_token="123:token",
            chat_id="-100123",
        ),
        opener=fake_open,
    )

    backend.send(
        Notification(
            kind="alert",
            alert_id="9f8e7d",
            alert_state="firing",
            backend_id="main_telegram",
            sensor_id="freezer_1",
            sensor_name="Freezer 1",
            sensor_topic="measurements/freezer1",
            rule_id="high_warn",
            severity="warning",
            title="Freezer 1 warning",
            message="Temperature is above limit",
            value=6.3,
            threshold=5.0,
            direction="above",
            occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )

    assert captured["url"].endswith("/sendMessage")
    assert captured["payload"]["chat_id"] == "-100123"
    assert (
        captured["payload"]["text"] == "Freezer 1 warning\n\nTemperature is above limit"
    )
    assert (
        captured["payload"]["reply_markup"]["inline_keyboard"][0][0]["text"]
        == "Acknowledge"
    )
    assert (
        captured["payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == "ack:9f8e7d"
    )
    assert captured["timeout"] == 10


def test_telegram_callback_payload_round_trips() -> None:
    """Alert ids should survive the compact Telegram callback encoding."""
    payload = build_telegram_callback_data("abc123")

    assert payload == "ack:abc123"
    assert parse_telegram_callback_data(payload) == "abc123"
    assert parse_telegram_callback_data("noop:abc123") is None


def test_telegram_backend_polls_callback_queries_and_tracks_offset() -> None:
    """Polling should return only acknowledgement callbacks and advance the update offset."""
    requests = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self._body).encode("utf-8")

    responses = [
        {
            "ok": True,
            "result": [
                {
                    "update_id": 17,
                    "callback_query": {
                        "id": "callback-1",
                        "data": "ack:alert-123",
                        "from": {"id": 77, "username": "alice"},
                        "message": {
                            "message_id": 55,
                            "text": "Freezer 1 warning\n\nTemperature is above limit",
                            "chat": {"id": -1001},
                        },
                    },
                }
            ],
        },
        {"ok": True, "result": []},
    ]

    def fake_open(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse(responses.pop(0))

    backend = TelegramBackend(
        TelegramBackendConfig(
            id="main_telegram",
            type="telegram",
            bot_token="123:token",
            chat_id="-100123",
            polling_timeout_seconds=2,
        ),
        opener=fake_open,
    )

    interactions = backend.poll_interactions()
    second = backend.poll_interactions()

    assert len(interactions) == 1
    assert interactions[0].alert_id == "alert-123"
    assert interactions[0].acknowledged_by == "@alice"
    assert second == []
    assert requests[0]["url"].endswith("/getUpdates")
    assert requests[0]["payload"]["allowed_updates"] == ["callback_query"]
    assert requests[1]["payload"]["offset"] == 18


def test_telegram_backend_answers_callback_and_edits_message_after_ack() -> None:
    """Successful acknowledgements should answer the callback and update the message."""
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"ok": True, "result": True}).encode("utf-8")

    def fake_open(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    backend = TelegramBackend(
        TelegramBackendConfig(
            id="main_telegram",
            type="telegram",
            bot_token="123:token",
            chat_id="-100123",
        ),
        opener=fake_open,
    )

    backend.finalize_acknowledgement(
        TelegramInteraction(
            backend_id="main_telegram",
            callback_query_id="callback-1",
            alert_id="alert-123",
            acknowledged_by="@alice",
            chat_id="-100123",
            message_id=55,
            message_text="Freezer 1 warning\n\nTemperature is above limit",
        ),
        AcknowledgementResult(
            status=ACK_STATUS_ACKNOWLEDGED,
            alert=AlertInstance(
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
            ),
        ),
    )

    assert requests[0]["url"].endswith("/answerCallbackQuery")
    assert requests[0]["payload"]["text"] == "Acknowledged by @alice"
    assert requests[1]["url"].endswith("/editMessageText")
    assert (
        "Acknowledged by @alice at 2025-01-01 10:16:00Z"
        in requests[1]["payload"]["text"]
    )
