"""Tests for the MQTT runtime wiring."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import paho.mqtt.client as mqtt

from mqtt_alerts.config import AppConfig, MqttConfig, NtfyBackendConfig, SensorConfig, StateConfig
from mqtt_alerts.config import RuleConfig
from mqtt_alerts.engine import AlertEngine
from mqtt_alerts.notifications import NotificationDispatcher
from mqtt_alerts.persistence import SQLiteStateStore
from mqtt_alerts.runtime import MqttAlertsApp


def test_on_connect_subscribes_when_reason_code_is_success(tmp_path) -> None:
    """Successful MQTT v2 reason codes should subscribe without int() casting."""
    app = MqttAlertsApp(
        config=_build_config(str(tmp_path / "state.sqlite3")),
        state_store=SQLiteStateStore(str(tmp_path / "state.sqlite3")),
        dispatcher=NotificationDispatcher({}),
        engine=AlertEngine((_build_sensor(),)),
    )
    subscriptions = []
    client = SimpleNamespace(subscribe=subscriptions.append)
    reason_code = mqtt.ReasonCode(mqtt.PacketTypes.CONNACK, "Success")

    app._on_connect(client, None, None, reason_code)  # pylint: disable=protected-access

    assert subscriptions == ["measurements/A118636/27054"]


def _build_config(database_path: str) -> AppConfig:
    return AppConfig(
        mqtt=MqttConfig(host="localhost", topic_prefix="measurements"),
        state=StateConfig(database=database_path),
        notification_backends=(
            NtfyBackendConfig(
                id="main_ntfy",
                type="ntfy",
                server="https://ntfy.sh",
                topic="topic",
            ),
        ),
        sensors=(_build_sensor(),),
    )


def _build_sensor() -> SensorConfig:
    return SensorConfig(
        id="kitchen_fridge",
        name="Kitchen fridge",
        topic="measurements/A118636/27054",
        value_field="reading",
        rules=(
            RuleConfig(
                id="high_warn",
                direction="above",
                threshold=6.0,
                hold_for=timedelta(minutes=20),
                severity="warning",
                backend="main_ntfy",
            ),
        ),
    )
