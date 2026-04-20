"""Notification backends for mqtt-alerts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import quote
from urllib.request import Request
from urllib.request import urlopen

from mqtt_alerts.config import NtfyBackendConfig, NotificationBackendConfig
from mqtt_alerts.models import Notification


class NotificationError(Exception):
    """Raised when a notification cannot be delivered."""


class NotificationBackend(Protocol):  # pylint: disable=too-few-public-methods
    """Interface implemented by delivery backends."""

    def send(self, notification: Notification) -> None:
        """Deliver one notification."""


class NotificationDispatcher:  # pylint: disable=too-few-public-methods
    """Route notifications to the configured backend implementation."""

    def __init__(self, backends: dict[str, NotificationBackend]) -> None:
        self._backends = backends

    def send(self, notification: Notification) -> None:
        """Send a notification through the backend referenced by the rule."""
        try:
            backend = self._backends[notification.backend_id]
        except KeyError as error:
            raise NotificationError(
                f"unknown notification backend {notification.backend_id!r}"
            ) from error
        backend.send(notification)


class NtfyBackend:  # pylint: disable=too-few-public-methods
    """Send notifications to an ntfy topic via HTTP POST."""

    def __init__(
        self,
        config: NtfyBackendConfig,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._config = config
        self._opener = opener

    def send(self, notification: Notification) -> None:
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
        except Exception as error:  # pragma: no cover - exercised through tests with fakes
            raise NotificationError(
                f"failed to send notification to ntfy backend {self._config.id!r}: {error}"
            ) from error


def build_backends(
    configs: tuple[NotificationBackendConfig, ...],
) -> dict[str, NotificationBackend]:
    """Instantiate the concrete backend implementations."""
    backends: dict[str, NotificationBackend] = {}
    for config in configs:
        if isinstance(config, NtfyBackendConfig):
            backends[config.id] = NtfyBackend(config)
            continue
        raise NotificationError(f"unsupported backend config type {type(config)!r}")
    return backends


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
