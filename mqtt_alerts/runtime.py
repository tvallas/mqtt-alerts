"""Application wiring and MQTT runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time

import paho.mqtt.client as mqtt

from mqtt_alerts.config import AppConfig, ConfigError, load_config
from mqtt_alerts.engine import AlertEngine
from mqtt_alerts.models import ACK_STATUS_ACKNOWLEDGED, ACK_STATUS_ALREADY_ACKNOWLEDGED
from mqtt_alerts.models import ACK_STATUS_NOT_ACTIVE, ACK_STATUS_NOT_FOUND
from mqtt_alerts.models import ALERT_STATE_RESOLVED
from mqtt_alerts.models import AcknowledgementResult, EvaluationResult, RuleKey
from mqtt_alerts.models import RuleState
from mqtt_alerts.notifications import (
    NotificationDispatcher,
    NotificationError,
    PushoverBackend,
    TelegramBackend,
)
from mqtt_alerts.notifications import build_backends
from mqtt_alerts.persistence import SQLiteStateStore

LOGGER = logging.getLogger(__name__)


class ApplicationError(Exception):
    """Raised on fatal application startup problems."""


class MqttAlertsApp:  # pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-positional-arguments
    """Daemon-style application process for MQTT alerting."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        config: AppConfig,
        state_store: SQLiteStateStore,
        dispatcher: NotificationDispatcher,
        engine: AlertEngine,
        config_path: str | None = None,
        config_mtime_ns: int | None = None,
        reload_interval_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self._state_store = state_store
        self._dispatcher = dispatcher
        self._engine = engine
        self._config_path = Path(config_path) if config_path is not None else None
        self._config_mtime_ns = config_mtime_ns
        self._reload_interval_seconds = reload_interval_seconds
        self._client: mqtt.Client | None = None

    @classmethod
    def from_config_file(cls, path: str) -> "MqttAlertsApp":
        """Build a fully wired application from a YAML config file."""
        config_path = Path(path)
        config = load_config(config_path)
        state_store = SQLiteStateStore(config.state.database)
        engine = AlertEngine(config.sensors, initial_state=state_store.load_states())
        dispatcher = NotificationDispatcher(
            build_backends(config.notification_backends)
        )
        return cls(
            config=config,
            state_store=state_store,
            dispatcher=dispatcher,
            engine=engine,
            config_path=str(config_path),
            config_mtime_ns=_read_config_mtime_ns(config_path),
        )

    def run_forever(self) -> None:
        """Connect to MQTT and process messages indefinitely."""
        client = self._create_client()
        self._client = client
        try:
            client.connect(
                host=self.config.mqtt.host,
                port=self.config.mqtt.port,
                keepalive=self.config.mqtt.keepalive,
            )
        except OSError as error:
            raise ApplicationError(
                f"failed to connect to MQTT broker: {error}"
            ) from error

        LOGGER.info(
            "connecting to MQTT broker at %s:%s",
            self.config.mqtt.host,
            self.config.mqtt.port,
        )
        try:
            while True:
                self._reload_config_if_changed()
                self._poll_notification_backends()
                self._send_due_reminders()
                loop_result = client.loop(timeout=self._reload_interval_seconds)
                if loop_result == mqtt.MQTT_ERR_SUCCESS:
                    continue
                self._handle_loop_error(client, loop_result)
        except KeyboardInterrupt:
            LOGGER.info("shutting down")
        finally:
            client.disconnect()
            self._state_store.close()

    def _create_client(self) -> mqtt.Client:
        client_id = self.config.mqtt.client_id or ""
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        client.enable_logger(LOGGER)
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        if self.config.mqtt.username is not None:
            client.username_pw_set(
                username=self.config.mqtt.username,
                password=self.config.mqtt.password,
            )
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: object,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None = None,
    ) -> None:
        if reason_code.is_failure:
            LOGGER.error("MQTT connection failed with reason code %s", reason_code)
            return

        for topic in self._engine.subscribed_topics():
            client.subscribe(topic)
            LOGGER.info("subscribed to %s", topic)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            payload = _decode_payload(message.payload)
            result = self._engine.process_message(
                topic=message.topic,
                payload=payload,
                observed_at=datetime.now(timezone.utc),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            LOGGER.warning("skipping message on topic %s: %s", message.topic, error)
            return

        self._deliver_notifications(result)
        self._cancel_resolved_pushover_retries(result)
        self._state_store.save_updates(result.state_updates, result.alert_updates)

    def _send_due_reminders(self) -> None:
        result = self._engine.process_reminders(datetime.now(timezone.utc))
        if not result.notifications:
            return
        self._deliver_notifications(result)
        self._state_store.save_updates(result.state_updates, result.alert_updates)

    def _deliver_notifications(self, result: EvaluationResult) -> None:
        for notification in result.notifications:
            key = RuleKey(
                sensor_id=notification.sensor_id, rule_id=notification.rule_id
            )
            try:
                delivery = self._dispatcher.send(notification)
                if delivery is not None and delivery.receipt is not None:
                    receipt_result = self._engine.record_delivery_receipt(
                        delivery.alert_id,
                        delivery.receipt,
                    )
                    result.state_updates.update(receipt_result.state_updates)
                    result.alert_updates.update(receipt_result.alert_updates)
                LOGGER.info(
                    "sent %s %s notification for sensor=%s rule=%s",
                    notification.kind,
                    notification.severity,
                    notification.sensor_id,
                    notification.rule_id,
                )
            except NotificationError as error:
                previous_state = _rollback_state_after_delivery_error(result, key)
                if previous_state is not None:
                    self._engine.restore_state(key, previous_state)
                LOGGER.error("notification delivery failed: %s", error)

    def _poll_notification_backends(self) -> None:
        now = datetime.now(timezone.utc)
        for backend in self._telegram_backends():
            if not backend.ready_to_poll(now):
                continue
            try:
                interactions = backend.poll_interactions(now)
            except NotificationError as error:
                LOGGER.warning(
                    "Telegram polling failed for backend %s: %s",
                    backend.backend_id,
                    error,
                )
                continue

            for interaction in interactions:
                result = self._engine.acknowledge_alert(
                    interaction.alert_id,
                    acknowledged_at=now,
                    acknowledged_by=interaction.acknowledged_by,
                )
                if result.state_updates or result.alert_updates:
                    self._state_store.save_updates(
                        result.state_updates,
                        result.alert_updates,
                    )
                _log_acknowledgement_result(result, interaction.alert_id)
                try:
                    backend.finalize_acknowledgement(interaction, result)
                except NotificationError as error:
                    LOGGER.warning(
                        "Telegram acknowledgement finalization failed for backend %s: %s",
                        backend.backend_id,
                        error,
                    )

        for backend in self._pushover_backends():
            if not backend.ready_to_poll(now):
                continue
            alerts = self._engine.active_alerts_for_backend(backend.backend_id)
            if not alerts:
                continue
            try:
                acknowledgements = backend.poll_receipts(alerts, now)
            except NotificationError as error:
                LOGGER.warning(
                    "Pushover receipt polling failed for backend %s: %s",
                    backend.backend_id,
                    error,
                )
                continue
            for acknowledgement in acknowledgements:
                result = self._engine.acknowledge_alert(
                    acknowledgement.alert_id,
                    acknowledged_at=acknowledgement.acknowledged_at,
                    acknowledged_by=acknowledgement.acknowledged_by,
                )
                if result.state_updates or result.alert_updates:
                    self._state_store.save_updates(
                        result.state_updates,
                        result.alert_updates,
                    )
                _log_acknowledgement_result(result, acknowledgement.alert_id)

    def _reload_config_if_changed(self) -> None:
        if self._config_path is None:
            return

        current_mtime_ns = _read_config_mtime_ns(self._config_path)
        if current_mtime_ns is None or current_mtime_ns == self._config_mtime_ns:
            return

        previous_topics = set(self._engine.subscribed_topics())
        try:
            new_config = load_config(self._config_path)
        except ConfigError as error:
            self._config_mtime_ns = current_mtime_ns
            LOGGER.error(
                "config reload failed, keeping previous configuration: %s", error
            )
            return

        if new_config.mqtt != self.config.mqtt:
            self._config_mtime_ns = current_mtime_ns
            LOGGER.warning(
                "config changed MQTT connection settings; "
                "restart required before changes take effect"
            )
            return

        if new_config.state != self.config.state:
            self._config_mtime_ns = current_mtime_ns
            LOGGER.warning(
                "config changed state persistence settings; "
                "restart required before changes take effect"
            )
            return

        self._dispatcher = NotificationDispatcher(
            build_backends(new_config.notification_backends)
        )
        self._engine = AlertEngine(
            new_config.sensors,
            initial_state=self._state_store.load_states(),
        )
        self.config = new_config
        self._config_mtime_ns = current_mtime_ns
        self._update_subscriptions(
            previous_topics, set(self._engine.subscribed_topics())
        )
        LOGGER.info("reloaded configuration from %s", self._config_path)

    def _handle_loop_error(self, client: mqtt.Client, loop_result: int) -> None:
        if loop_result == mqtt.MQTT_ERR_AGAIN:
            return

        LOGGER.warning("MQTT loop returned %s", mqtt.error_string(loop_result))
        try:
            client.reconnect()
        except OSError as error:
            LOGGER.warning("failed to reconnect to MQTT broker: %s", error)
            time.sleep(self._reload_interval_seconds)

    def _update_subscriptions(
        self,
        previous_topics: set[str],
        new_topics: set[str],
    ) -> None:
        client = self._client
        if client is None or not client.is_connected():
            return

        for topic in sorted(previous_topics - new_topics):
            client.unsubscribe(topic)
            LOGGER.info("unsubscribed from %s", topic)

        for topic in sorted(new_topics - previous_topics):
            client.subscribe(topic)
            LOGGER.info("subscribed to %s", topic)

    def _telegram_backends(self) -> list[TelegramBackend]:
        return [
            backend
            for backend in self._dispatcher.backends.values()
            if isinstance(backend, TelegramBackend)
        ]

    def _pushover_backends(self) -> list[PushoverBackend]:
        return [
            backend
            for backend in self._dispatcher.backends.values()
            if isinstance(backend, PushoverBackend)
        ]

    def _cancel_resolved_pushover_retries(self, result: EvaluationResult) -> None:
        for alert in result.alert_updates.values():
            if alert.state != ALERT_STATE_RESOLVED or alert.delivery_receipt is None:
                continue
            backend = self._dispatcher.backends.get(alert.backend_id)
            if not isinstance(backend, PushoverBackend):
                continue
            try:
                backend.cancel_receipt(alert.delivery_receipt)
            except NotificationError as error:
                LOGGER.warning(
                    "Pushover retry cancellation failed for backend %s alert=%s: %s",
                    backend.backend_id,
                    alert.id,
                    error,
                )


def _decode_payload(raw_payload: bytes) -> dict[str, object]:
    payload = json.loads(raw_payload.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("payload must decode to a JSON object")
    return payload


def _rollback_state_after_delivery_error(
    result: EvaluationResult, key: RuleKey
) -> RuleState | None:
    previous_state = result.rollback_states.get(key)
    if previous_state is None:
        return None
    result.state_updates[key] = previous_state
    current_alert = previous_state.current_alert
    if current_alert is not None:
        result.alert_updates[current_alert.id] = current_alert.copy()
    return previous_state


def _log_acknowledgement_result(result: AcknowledgementResult, alert_id: str) -> None:
    alert = result.alert
    if result.status == ACK_STATUS_ACKNOWLEDGED and alert is not None:
        LOGGER.info(
            "acknowledged alert id=%s sensor=%s rule=%s by=%s",
            alert.id,
            alert.sensor_id,
            alert.rule_id,
            alert.acknowledged_by or "unknown",
        )
        return
    if result.status == ACK_STATUS_ALREADY_ACKNOWLEDGED:
        LOGGER.debug("alert id=%s was already acknowledged", alert_id)
        return
    if result.status == ACK_STATUS_NOT_ACTIVE:
        LOGGER.info("alert id=%s is no longer active", alert_id)
        return
    if result.status == ACK_STATUS_NOT_FOUND:
        LOGGER.info("alert id=%s was not found for acknowledgement", alert_id)


def _read_config_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError as error:
        LOGGER.warning("failed to stat config file %s: %s", path, error)
        return None


def run_application(config_path: str) -> None:
    """Convenience helper used by the CLI."""
    app = MqttAlertsApp.from_config_file(config_path)
    app.run_forever()
