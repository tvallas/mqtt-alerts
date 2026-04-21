"""Notification backends for mqtt-alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Protocol
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from mqtt_alerts.config import (
    NtfyBackendConfig,
    NotificationBackendConfig,
    PushoverBackendConfig,
    TelegramBackendConfig,
)
from mqtt_alerts.models import ACK_STATUS_ACKNOWLEDGED, ACK_STATUS_ALREADY_ACKNOWLEDGED
from mqtt_alerts.models import ACK_STATUS_NOT_ACTIVE, ACK_STATUS_NOT_FOUND
from mqtt_alerts.models import AcknowledgementResult, AlertInstance, Notification
from mqtt_alerts.models import NotificationDelivery, ReceiptAcknowledgement


class NotificationError(Exception):
    """Raised when a notification cannot be delivered."""


class NotificationBackend(Protocol):  # pylint: disable=too-few-public-methods
    """Interface implemented by delivery backends."""

    def send(self, notification: Notification) -> NotificationDelivery | None:
        """Deliver one notification."""


@dataclass(frozen=True)
class TelegramInteraction:
    """One acknowledgement callback received from Telegram."""

    backend_id: str
    callback_query_id: str
    alert_id: str
    acknowledged_by: str | None
    chat_id: str | None
    message_id: int | None
    message_text: str | None


@dataclass(frozen=True)
class TelegramSentMessage:
    """One Telegram message sent for an active alert."""

    chat_id: str
    message_id: int
    text: str | None


class NotificationDispatcher:  # pylint: disable=too-few-public-methods
    """Route notifications to the configured backend implementation."""

    def __init__(self, backends: dict[str, NotificationBackend]) -> None:
        self._backends = backends

    @property
    def backends(self) -> dict[str, NotificationBackend]:
        """Expose configured backends to the runtime."""
        return self._backends

    def send(self, notification: Notification) -> NotificationDelivery | None:
        """Send a notification through the backend referenced by the rule."""
        try:
            backend = self._backends[notification.backend_id]
        except KeyError as error:
            raise NotificationError(
                f"unknown notification backend {notification.backend_id!r}"
            ) from error
        return backend.send(notification)


class NtfyBackend:  # pylint: disable=too-few-public-methods
    """Send notifications to an ntfy topic via HTTP POST."""

    def __init__(
        self,
        config: NtfyBackendConfig,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._config = config
        self._opener = opener

    def send(self, notification: Notification) -> NotificationDelivery | None:
        """Deliver a notification to the configured ntfy topic."""
        request = Request(
            url=_build_ntfy_url(self._config.server, self._config.topic),
            data=notification.message.encode("utf-8"),
            headers=_build_ntfy_headers(notification),
            method="POST",
        )

        try:
            with self._opener(request, timeout=10) as response:
                response.read()
        except (
            Exception
        ) as error:  # pragma: no cover - exercised through tests with fakes
            raise NotificationError(
                f"failed to send notification to ntfy backend {self._config.id!r}: {error}"
            ) from error


class PushoverBackend:  # pylint: disable=too-many-instance-attributes
    """Send notifications through the Pushover Message API."""

    def __init__(
        self,
        config: PushoverBackendConfig,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._config = config
        self._opener = opener
        self._next_poll_at: datetime | None = None

    @property
    def backend_id(self) -> str:
        """Return the configured backend id."""
        return self._config.id

    def ready_to_poll(self, now: datetime) -> bool:
        """Whether the configured receipt polling interval allows another poll."""
        if not self._config.polling_enabled:
            return False
        if self._next_poll_at is None:
            return True
        return now >= self._next_poll_at

    def send(self, notification: Notification) -> NotificationDelivery | None:
        """Deliver a notification to Pushover."""
        payload = _build_pushover_payload(self._config, notification)
        response = self._request_json(
            "messages",
            "https://api.pushover.net/1/messages.json",
            payload,
            timeout=10,
        )
        receipt = response.get("receipt")
        if isinstance(receipt, str) and receipt.strip():
            return NotificationDelivery(
                alert_id=notification.alert_id,
                backend_id=notification.backend_id,
                receipt=receipt.strip(),
            )
        return None

    def poll_receipts(
        self,
        alerts: list[AlertInstance],
        now: datetime | None = None,
    ) -> list[ReceiptAcknowledgement]:
        """Poll Pushover emergency receipts for acknowledgements."""
        current_time = now or datetime.now(timezone.utc)
        if not self.ready_to_poll(current_time):
            return []

        self._next_poll_at = current_time + timedelta(
            seconds=self._config.polling_interval_seconds
        )
        acknowledgements: list[ReceiptAcknowledgement] = []
        for alert in alerts:
            if alert.delivery_receipt is None:
                continue
            response = self._request_json(
                "receipt",
                (
                    "https://api.pushover.net/1/receipts/"
                    f"{quote(alert.delivery_receipt, safe='')}.json"
                    f"?{urlencode({'token': self._config.api_token})}"
                ),
                None,
                timeout=10,
                method="GET",
            )
            if response.get("acknowledged") != 1:
                continue
            acknowledged_at = _parse_pushover_timestamp(response.get("acknowledged_at"))
            acknowledgements.append(
                ReceiptAcknowledgement(
                    alert_id=alert.id,
                    acknowledged_at=acknowledged_at or current_time,
                    acknowledged_by=_format_pushover_acknowledger(response),
                )
            )
        return acknowledgements

    def cancel_receipt(self, receipt: str) -> None:
        """Cancel retries for one emergency-priority Pushover receipt."""
        self._request_json(
            "cancel receipt",
            (
                "https://api.pushover.net/1/receipts/"
                f"{quote(receipt, safe='')}/cancel.json"
            ),
            {"token": self._config.api_token},
            timeout=10,
        )

    def _request_json(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        action: str,
        url: str,
        payload: dict[str, Any] | None,
        timeout: int,
        method: str = "POST",
    ) -> dict[str, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url=url, data=data, headers=headers, method=method)

        try:
            with self._opener(request, timeout=timeout) as response:
                raw_body = response.read()
        except (
            Exception
        ) as error:  # pragma: no cover - exercised through tests with fakes
            raise NotificationError(
                f"failed to call Pushover backend {self._config.id!r}: {error}"
            ) from error

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NotificationError(
                f"Pushover backend {self._config.id!r} returned invalid JSON: {error}"
            ) from error

        if body.get("status") != 1:
            errors = body.get("errors")
            if isinstance(errors, list):
                detail = ", ".join(str(item) for item in errors)
            else:
                detail = str(errors or "unknown error")
            raise NotificationError(
                f"Pushover backend {self._config.id!r} {action} failed: {detail}"
            )
        return body


class TelegramBackend:  # pylint: disable=too-many-instance-attributes
    """Send alerts to Telegram and poll acknowledgement callbacks."""

    def __init__(
        self,
        config: TelegramBackendConfig,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._config = config
        self._opener = opener
        self._next_update_id: int | None = None
        self._next_poll_at: datetime | None = None
        self._alert_messages: dict[str, list[TelegramSentMessage]] = {}
        self._seen_callback_query_ids: set[str] = set()

    @property
    def backend_id(self) -> str:
        """Return the configured backend id."""
        return self._config.id

    def polling_enabled(self) -> bool:
        """Whether Telegram polling is enabled for this backend."""
        return self._config.polling_enabled

    def ready_to_poll(self, now: datetime) -> bool:
        """Whether the configured backoff interval allows another poll."""
        if not self._config.polling_enabled:
            return False
        if self._next_poll_at is None:
            return True
        return now >= self._next_poll_at

    def send(self, notification: Notification) -> NotificationDelivery | None:
        """Send one alert or recovery message to the configured Telegram chat."""
        message_text = _build_telegram_message_text(notification)
        payload: dict[str, Any] = {
            "chat_id": self._config.chat_id,
            "text": message_text,
        }
        if notification.kind in {"alert", "reminder"}:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Acknowledge",
                            "callback_data": build_telegram_callback_data(
                                notification.alert_id
                            ),
                        }
                    ]
                ]
            }
        response = self._request_json("sendMessage", payload, timeout=10)
        if notification.kind in {"alert", "reminder"}:
            self._remember_alert_message(
                notification.alert_id,
                response,
                message_text,
            )

    def poll_interactions(
        self, now: datetime | None = None
    ) -> list[TelegramInteraction]:
        """Fetch new Telegram callback queries via long polling."""
        if not self._config.polling_enabled:
            return []

        current_time = now or datetime.now(timezone.utc)
        if not self.ready_to_poll(current_time):
            return []

        payload: dict[str, Any] = {
            "timeout": self._config.polling_timeout_seconds,
            "allowed_updates": ["callback_query"],
        }
        if self._next_update_id is not None:
            payload["offset"] = self._next_update_id

        response = self._request_json(
            "getUpdates",
            payload,
            timeout=max(1, self._config.polling_timeout_seconds) + 5,
        )
        self._next_poll_at = current_time + timedelta(
            seconds=self._config.polling_interval_seconds
        )
        max_update_id = self._next_update_id
        interactions: list[TelegramInteraction] = []
        for update in response.get("result", []):
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                max_update_id = (
                    update_id
                    if max_update_id is None
                    else max(max_update_id, update_id)
                )
            interaction = _parse_telegram_interaction(self._config.id, update)
            if interaction is None:
                continue
            if interaction.callback_query_id in self._seen_callback_query_ids:
                continue
            self._seen_callback_query_ids.add(interaction.callback_query_id)
            interactions.append(interaction)
        if max_update_id is not None:
            self._next_update_id = max_update_id + 1
        return interactions

    def finalize_acknowledgement(
        self,
        interaction: TelegramInteraction,
        result: AcknowledgementResult,
    ) -> None:
        """Answer the callback query and update the Telegram message when practical."""
        try:
            self._request_json(
                "answerCallbackQuery",
                {
                    "callback_query_id": interaction.callback_query_id,
                    "text": _build_callback_answer_text(result),
                },
                timeout=10,
            )
        except NotificationError:
            pass

        if result.status not in {
            ACK_STATUS_ACKNOWLEDGED,
            ACK_STATUS_ALREADY_ACKNOWLEDGED,
        }:
            return
        if result.alert is None:
            return

        for message in self._messages_to_update_after_ack(interaction):
            self._update_acknowledged_message(message, result.alert)

    def _request_json(
        self,
        method: str,
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        request = Request(
            url=f"{_build_telegram_base_url(self._config.bot_token)}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with self._opener(request, timeout=timeout) as response:
                raw_body = response.read()
        except (
            Exception
        ) as error:  # pragma: no cover - exercised through tests with fakes
            raise NotificationError(
                f"failed to call Telegram backend {self._config.id!r}: {error}"
            ) from error

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NotificationError(
                f"Telegram backend {self._config.id!r} returned invalid JSON: {error}"
            ) from error

        if not body.get("ok"):
            raise NotificationError(
                f"Telegram backend {self._config.id!r} request {method!r} failed: "
                f"{body.get('description', 'unknown error')}"
            )
        return body

    def _remember_alert_message(
        self,
        alert_id: str,
        response: dict[str, Any],
        message_text: str,
    ) -> None:
        result = response.get("result")
        if not isinstance(result, dict):
            return
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            return
        self._alert_messages.setdefault(alert_id, []).append(
            TelegramSentMessage(
                chat_id=self._config.chat_id,
                message_id=message_id,
                text=message_text,
            )
        )

    def _messages_to_update_after_ack(
        self,
        interaction: TelegramInteraction,
    ) -> list[TelegramSentMessage]:
        messages = self._alert_messages.pop(interaction.alert_id, [])
        if interaction.chat_id is not None and interaction.message_id is not None:
            messages.append(
                TelegramSentMessage(
                    chat_id=interaction.chat_id,
                    message_id=interaction.message_id,
                    text=interaction.message_text,
                )
            )

        deduplicated: dict[tuple[str, int], TelegramSentMessage] = {}
        for message in messages:
            deduplicated[(message.chat_id, message.message_id)] = message
        return list(deduplicated.values())

    def _update_acknowledged_message(
        self,
        message: TelegramSentMessage,
        alert: AlertInstance,
    ) -> None:
        edit_payload: dict[str, Any] = {
            "chat_id": message.chat_id,
            "message_id": message.message_id,
            "reply_markup": {"inline_keyboard": []},
        }
        if message.text is not None:
            edit_payload["text"] = _append_acknowledgement_note(message.text, alert)
            try:
                self._request_json("editMessageText", edit_payload, timeout=10)
                return
            except NotificationError:
                pass

        try:
            self._request_json("editMessageReplyMarkup", edit_payload, timeout=10)
        except NotificationError:
            pass


def build_backends(
    configs: tuple[NotificationBackendConfig, ...],
) -> dict[str, NotificationBackend]:
    """Instantiate the concrete backend implementations."""
    backends: dict[str, NotificationBackend] = {}
    for config in configs:
        if isinstance(config, NtfyBackendConfig):
            backends[config.id] = NtfyBackend(config)
            continue
        if isinstance(config, PushoverBackendConfig):
            backends[config.id] = PushoverBackend(config)
            continue
        if isinstance(config, TelegramBackendConfig):
            backends[config.id] = TelegramBackend(config)
            continue
        raise NotificationError(f"unsupported backend config type {type(config)!r}")
    return backends


def build_telegram_callback_data(alert_id: str) -> str:
    """Encode a compact callback payload that identifies one alert instance."""
    return f"ack:{alert_id}"


def parse_telegram_callback_data(value: str) -> str | None:
    """Return the alert id carried by a Telegram callback payload."""
    if not value.startswith("ack:"):
        return None
    alert_id = value[4:].strip()
    if not alert_id:
        return None
    return alert_id


def _build_ntfy_url(server: str, topic: str) -> str:
    return f"{server.rstrip('/')}/{quote(topic, safe='')}"


def _build_ntfy_headers(notification: Notification) -> dict[str, str]:
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Title": notification.title,
        "Priority": str(_map_priority(notification.severity)),
    }
    tags = _map_tags(notification.severity)
    if tags:
        headers["Tags"] = tags
    return headers


def _build_pushover_payload(
    config: PushoverBackendConfig,
    notification: Notification,
) -> dict[str, str | int]:
    priority = _map_pushover_priority(config, notification)
    payload: dict[str, str | int] = {
        "token": config.api_token,
        "user": config.user_key,
        "title": notification.title,
        "message": notification.message,
        "priority": priority,
        "timestamp": int(notification.occurred_at.timestamp()),
    }
    optional_values = {
        "device": config.device,
        "sound": config.sound,
        "url": config.url,
        "url_title": config.url_title,
    }
    for key, value in optional_values.items():
        if value is not None:
            payload[key] = value
    if priority == 2:
        payload["retry"] = config.emergency_retry_seconds
        payload["expire"] = config.emergency_expire_seconds
        payload["tags"] = f"mqtt-alerts,alert={notification.alert_id}"
    return payload


def _map_pushover_priority(
    config: PushoverBackendConfig,
    notification: Notification,
) -> int:
    if notification.kind == "recovery":
        return 0
    configured = config.priority_by_severity.get(notification.severity.lower())
    if configured is not None:
        return configured
    return {
        "low": 0,
        "warning": 1,
        "medium": 1,
        "high": 1,
        "critical": 2,
    }.get(notification.severity.lower(), 0)


def _parse_pushover_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, int) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _format_pushover_acknowledger(response: dict[str, Any]) -> str | None:
    user_key = response.get("acknowledged_by")
    device = response.get("acknowledged_by_device")
    if isinstance(user_key, str) and user_key.strip():
        if isinstance(device, str) and device.strip():
            return f"pushover user {user_key.strip()} on {device.strip()}"
        return f"pushover user {user_key.strip()}"
    return None


def _map_priority(severity: str) -> int:
    return {
        "low": 2,
        "warning": 3,
        "medium": 3,
        "high": 4,
        "critical": 5,
    }.get(severity.lower(), 3)


def _map_tags(severity: str) -> str:
    return {
        "low": "information_source",
        "warning": "warning",
        "medium": "warning",
        "high": "rotating_light",
        "critical": "rotating_light",
    }.get(severity.lower(), "warning")


def _build_telegram_base_url(bot_token: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}"


def _build_telegram_message_text(notification: Notification) -> str:
    if notification.kind == "recovery" and notification.acknowledged_by:
        return (
            f"{notification.title}\n\n{notification.message}\n\n"
            f"Acknowledged by: {notification.acknowledged_by}"
        )
    return f"{notification.title}\n\n{notification.message}"


def _parse_telegram_interaction(
    backend_id: str,
    update: dict[str, Any],
) -> TelegramInteraction | None:
    callback_query = update.get("callback_query")
    if not isinstance(callback_query, dict):
        return None

    callback_query_id = callback_query.get("id")
    if not isinstance(callback_query_id, str) or not callback_query_id.strip():
        return None

    alert_id = parse_telegram_callback_data(str(callback_query.get("data", "")))
    if alert_id is None:
        return None

    message = callback_query.get("message")
    chat_id = None
    message_id = None
    message_text = None
    if isinstance(message, dict):
        chat = message.get("chat")
        if isinstance(chat, dict) and "id" in chat:
            chat_id = str(chat["id"])
        raw_message_id = message.get("message_id")
        if isinstance(raw_message_id, int):
            message_id = raw_message_id
        raw_text = message.get("text")
        if isinstance(raw_text, str):
            message_text = raw_text

    return TelegramInteraction(
        backend_id=backend_id,
        callback_query_id=callback_query_id,
        alert_id=alert_id,
        acknowledged_by=_format_telegram_actor(callback_query.get("from")),
        chat_id=chat_id,
        message_id=message_id,
        message_text=message_text,
    )


def _format_telegram_actor(raw_user: Any) -> str | None:
    if not isinstance(raw_user, dict):
        return None
    username = raw_user.get("username")
    if isinstance(username, str) and username.strip():
        return f"@{username.strip()}"
    name_parts = []
    first_name = raw_user.get("first_name")
    if isinstance(first_name, str) and first_name.strip():
        name_parts.append(first_name.strip())
    last_name = raw_user.get("last_name")
    if isinstance(last_name, str) and last_name.strip():
        name_parts.append(last_name.strip())
    if name_parts:
        return " ".join(name_parts)
    user_id = raw_user.get("id")
    if isinstance(user_id, int):
        return f"telegram user {user_id}"
    return None


def _build_callback_answer_text(  # pylint: disable=too-many-return-statements
    result: AcknowledgementResult,
) -> str:
    if result.status == ACK_STATUS_ACKNOWLEDGED:
        if result.alert is not None and result.alert.acknowledged_by:
            return f"Acknowledged by {result.alert.acknowledged_by}"
        return "Alert acknowledged"
    if result.status == ACK_STATUS_ALREADY_ACKNOWLEDGED:
        if result.alert is not None and result.alert.acknowledged_by:
            return f"Already acknowledged by {result.alert.acknowledged_by}"
        return "Already acknowledged"
    if result.status == ACK_STATUS_NOT_ACTIVE:
        return "Alert is no longer active"
    if result.status == ACK_STATUS_NOT_FOUND:
        return "Alert no longer exists"
    return "Acknowledgement failed"


def _append_acknowledgement_note(message_text: str, alert: AlertInstance) -> str:
    if "Acknowledged by " in message_text:
        return message_text

    actor = alert.acknowledged_by or "unknown user"
    if alert.acknowledged_at is None:
        return f"{message_text}\n\nAcknowledged by {actor}"
    timestamp = alert.acknowledged_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%SZ"
    )
    return f"{message_text}\n\nAcknowledged by {actor} at {timestamp}"
