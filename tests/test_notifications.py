"""Tests for notification backends."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.parse import parse_qs

from mqtt_alerts.config import NtfyBackendConfig, PushoverBackendConfig
from mqtt_alerts.config import TelegramBackendConfig
from mqtt_alerts.models import (
    ACK_STATUS_ACKNOWLEDGED,
    AcknowledgementResult,
    AlertInstance,
)
from mqtt_alerts.models import Notification
from mqtt_alerts.notifications import NtfyBackend, PushoverBackend, TelegramBackend
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


def test_pushover_backend_sends_emergency_alert_and_returns_receipt() -> None:
    """Critical Pushover alerts should include emergency retry fields."""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {"status": 1, "request": "request-1", "receipt": "receipt-123"}
            ).encode("utf-8")

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = parse_qs(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    backend = PushoverBackend(
        PushoverBackendConfig(
            id="main_pushover",
            type="pushover",
            api_token="app-token",
            user_key="user-key",
            device="iphone",
            sound="siren",
            emergency_retry_seconds=60,
            emergency_expire_seconds=3600,
        ),
        opener=fake_open,
    )

    delivery = backend.send(
        Notification(
            kind="alert",
            alert_id="alert-1",
            alert_state="firing",
            backend_id="main_pushover",
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
            occurred_at=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        )
    )

    assert captured["url"] == "https://api.pushover.net/1/messages.json"
    assert captured["headers"]["Content-type"] == "application/x-www-form-urlencoded"
    assert captured["payload"]["token"] == ["app-token"]
    assert captured["payload"]["user"] == ["user-key"]
    assert captured["payload"]["device"] == ["iphone"]
    assert captured["payload"]["sound"] == ["siren"]
    assert captured["payload"]["priority"] == ["2"]
    assert captured["payload"]["retry"] == ["60"]
    assert captured["payload"]["expire"] == ["3600"]
    assert captured["payload"]["tags"] == ["mqtt-alerts,alert=alert-1"]
    assert captured["payload"]["timestamp"] == ["1735725600"]
    assert delivery is not None
    assert delivery.receipt == "receipt-123"


def test_pushover_backend_polls_receipts_for_acknowledgement() -> None:
    """Pushover receipt polling should surface acknowledged emergency alerts."""
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "status": 1,
                    "acknowledged": 1,
                    "acknowledged_at": 1735725900,
                    "acknowledged_by": "user-key",
                    "acknowledged_by_device": "iphone",
                }
            ).encode("utf-8")

    def fake_open(request, timeout):
        requests.append({"url": request.full_url, "method": request.get_method()})
        return FakeResponse()

    backend = PushoverBackend(
        PushoverBackendConfig(
            id="main_pushover",
            type="pushover",
            api_token="app-token",
            user_key="user-key",
        ),
        opener=fake_open,
    )
    alert = AlertInstance(
        id="alert-1",
        sensor_id="freezer_1",
        sensor_name="Freezer 1",
        sensor_topic="measurements/freezer1",
        rule_id="high_critical",
        severity="critical",
        backend_id="main_pushover",
        threshold=8.0,
        direction="above",
        started_at=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        state="firing",
        delivery_receipt="receipt-123",
    )

    acknowledgements = backend.poll_receipts(
        [alert],
        datetime(2025, 1, 1, 10, 6, tzinfo=timezone.utc),
    )

    assert requests == [
        {
            "url": (
                "https://api.pushover.net/1/receipts/"
                "receipt-123.json?token=app-token"
            ),
            "method": "GET",
        }
    ]
    assert len(acknowledgements) == 1
    assert acknowledgements[0].alert_id == "alert-1"
    assert acknowledgements[0].acknowledged_at == datetime(
        2025, 1, 1, 10, 5, tzinfo=timezone.utc
    )
    assert acknowledgements[0].acknowledged_by == "pushover user user-key on iphone"


def test_pushover_backend_cancels_emergency_retry_receipt() -> None:
    """Resolved alerts should be able to cancel active Pushover emergency retries."""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"status": 1, "request": "request-1"}).encode("utf-8")

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = parse_qs(request.data.decode("utf-8"))
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return FakeResponse()

    backend = PushoverBackend(
        PushoverBackendConfig(
            id="main_pushover",
            type="pushover",
            api_token="app-token",
            user_key="user-key",
        ),
        opener=fake_open,
    )

    backend.cancel_receipt("receipt-123")

    assert (
        captured["url"] == "https://api.pushover.net/1/receipts/receipt-123/cancel.json"
    )
    assert captured["payload"] == {"token": ["app-token"]}
    assert captured["method"] == "POST"


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

    backend.send(
        Notification(
            kind="reminder",
            alert_id="abc123",
            alert_state="firing",
            backend_id="main_telegram",
            sensor_id="freezer_1",
            sensor_name="Freezer 1",
            sensor_topic="measurements/freezer1",
            rule_id="high_warn",
            severity="warning",
            title="Reminder 1: Freezer 1 warning",
            message="Temperature is still above limit",
            value=6.3,
            threshold=5.0,
            direction="above",
            occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )

    assert (
        captured["payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == "ack:abc123"
    )


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


def test_telegram_backend_ignores_duplicate_callback_queries() -> None:
    """Repeated callback ids should not be processed more than once."""
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

    duplicate_update = {
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
    responses = [
        {"ok": True, "result": [{"update_id": 17, **duplicate_update}]},
        {"ok": True, "result": [{"update_id": 18, **duplicate_update}]},
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
        ),
        opener=fake_open,
    )

    first = backend.poll_interactions()
    second = backend.poll_interactions()

    assert len(first) == 1
    assert second == []


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


def test_telegram_backend_still_edits_message_when_callback_answer_fails() -> None:
    """Telegram may reject stale callback answers, but message edits are still useful."""
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

    def fake_open(request, timeout):
        requests.append(
            {
                "url": request.full_url,
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/answerCallbackQuery"):
            return FakeResponse({"ok": False, "description": "Bad Request"})
        return FakeResponse({"ok": True, "result": True})

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
    assert requests[1]["url"].endswith("/editMessageText")


def test_telegram_backend_updates_all_known_messages_after_ack() -> None:
    """Acknowledging one alert message should remove buttons from later reminders."""
    requests = []
    next_message_id = 100

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self._body).encode("utf-8")

    def fake_open(request, timeout):
        nonlocal next_message_id
        payload = json.loads(request.data.decode("utf-8"))
        requests.append(
            {
                "url": request.full_url,
                "payload": payload,
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/sendMessage"):
            next_message_id += 1
            return FakeResponse({"ok": True, "result": {"message_id": next_message_id}})
        return FakeResponse({"ok": True, "result": True})

    backend = TelegramBackend(
        TelegramBackendConfig(
            id="main_telegram",
            type="telegram",
            bot_token="123:token",
            chat_id="-100123",
        ),
        opener=fake_open,
    )
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

    for kind, title in (
        ("alert", "Freezer 1 warning"),
        ("reminder", "Reminder 1: Freezer 1 warning"),
    ):
        backend.send(
            Notification(
                kind=kind,
                alert_id="alert-123",
                alert_state="firing",
                backend_id="main_telegram",
                sensor_id="freezer_1",
                sensor_name="Freezer 1",
                sensor_topic="measurements/freezer1",
                rule_id="high_warn",
                severity="warning",
                title=title,
                message="Temperature is above limit",
                value=6.3,
                threshold=5.0,
                direction="above",
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )
        )

    backend.finalize_acknowledgement(
        TelegramInteraction(
            backend_id="main_telegram",
            callback_query_id="callback-1",
            alert_id="alert-123",
            acknowledged_by="@alice",
            chat_id="-100123",
            message_id=101,
            message_text="Freezer 1 warning\n\nTemperature is above limit",
        ),
        AcknowledgementResult(status=ACK_STATUS_ACKNOWLEDGED, alert=alert),
    )

    edits = [
        request for request in requests if request["url"].endswith("/editMessageText")
    ]
    assert [edit["payload"]["message_id"] for edit in edits] == [101, 102]
    assert all(
        edit["payload"]["reply_markup"] == {"inline_keyboard": []} for edit in edits
    )
    assert all("Acknowledged by @alice" in edit["payload"]["text"] for edit in edits)
