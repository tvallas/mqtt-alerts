"""Application wiring and MQTT runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging

import paho.mqtt.client as mqtt

from mqtt_alerts.config import AppConfig, load_config
from mqtt_alerts.engine import AlertEngine
from mqtt_alerts.models import EvaluationResult, RuleKey
from mqtt_alerts.notifications import NotificationDispatcher, NotificationError, build_backends
from mqtt_alerts.persistence import SQLiteStateStore


LOGGER = logging.getLogger(__name__)


class ApplicationError(Exception):
    """Raised on fatal application startup problems."""


class MqttAlertsApp:
    """Daemon-style application process for MQTT alerting."""

    def __init__(
        self,
        config: AppConfig,
        state_store: SQLiteStateStore,
        dispatcher: NotificationDispatcher,
        engine: AlertEngine,
    ) -> None:
        self.config = config
        self._state_store = state_store
        self._dispatcher = dispatcher
        self._engine = engine

    @classmethod
    def from_config_file(cls, path: str) -> "MqttAlertsApp":
        """Build a fully wired application from a YAML config file."""
        config = load_config(path)
        state_store = SQLiteStateStore(config.state.database)
        engine = AlertEngine(config.sensors, initial_state=state_store.load_states())
        dispatcher = NotificationDispatcher(build_backends(config.notification_backends))
        return cls(
            config=config,
            state_store=state_store,
            dispatcher=dispatcher,
            engine=engine,
        )

    def run_forever(self) -> None:
        """Connect to MQTT and process messages indefinitely."""
        client = self._create_client()
        try:
            client.connect(
                host=self.config.mqtt.host,
                port=self.config.mqtt.port,
                keepalive=self.config.mqtt.keepalive,
            )
        except OSError as error:
            raise ApplicationError(f"failed to connect to MQTT broker: {error}") from error

        LOGGER.info(
            "connecting to MQTT broker at %s:%s",
            self.config.mqtt.host,
            self.config.mqtt.port,
        )
        try:
            client.loop_forever()
        finally:
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
        if int(reason_code) != 0:
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
        for key, state in result.state_updates.items():
            self._state_store.save_state(key, state)

    def _deliver_notifications(self, result: EvaluationResult) -> None:
        for notification in result.notifications:
            key = RuleKey(sensor_id=notification.sensor_id, rule_id=notification.rule_id)
            try:
                self._dispatcher.send(notification)
                LOGGER.info(
                    "sent %s notification for sensor=%s rule=%s",
                    notification.severity,
                    notification.sensor_id,
                    notification.rule_id,
                )
            except NotificationError as error:
                _rollback_trigger_state(result, key)
                LOGGER.error("notification delivery failed: %s", error)


def _decode_payload(raw_payload: bytes) -> dict[str, object]:
    payload = json.loads(raw_payload.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("payload must decode to a JSON object")
    return payload


def _rollback_trigger_state(result: EvaluationResult, key: RuleKey) -> None:
    state = result.state_updates[key]
    state.alert_triggered = False
    state.triggered_at = None
    state.last_notification_at = None


def run_application(config_path: str) -> None:
    """Convenience helper used by the CLI."""
    app = MqttAlertsApp.from_config_file(config_path)
    app.run_forever()
