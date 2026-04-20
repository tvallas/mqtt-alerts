"""Tests for the MQTT runtime wiring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import paho.mqtt.client as mqtt

from mqtt_alerts.config import (
    AppConfig,
    MqttConfig,
    NtfyBackendConfig,
    SensorConfig,
    StateConfig,
)
from mqtt_alerts.config import RuleConfig
from mqtt_alerts.engine import AlertEngine
from mqtt_alerts.models import RuleKey
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


def test_reload_config_updates_topics_and_subscriptions(tmp_path: Path) -> None:
    """A valid sensor/rule reload should update the active subscriptions in place."""
    config_path = tmp_path / "config.yml"
    _write_config(config_path, sensor_topic="measurements/freezer1")
    app = MqttAlertsApp.from_config_file(str(config_path))
    subscriptions: list[str] = []
    unsubscriptions: list[str] = []
    app._client = SimpleNamespace(  # pylint: disable=protected-access
        is_connected=lambda: True,
        subscribe=subscriptions.append,
        unsubscribe=unsubscriptions.append,
    )

    _write_config(config_path, sensor_topic="measurements/freezer2")

    app._reload_config_if_changed()  # pylint: disable=protected-access

    assert app._engine.subscribed_topics() == [
        "measurements/freezer2"
    ]  # pylint: disable=protected-access
    assert subscriptions == ["measurements/freezer2"]
    assert unsubscriptions == ["measurements/freezer1"]
    app._state_store.close()  # pylint: disable=protected-access


def test_reload_config_rejects_mqtt_changes(tmp_path: Path, caplog) -> None:
    """MQTT connection changes require a restart instead of a hot reload."""
    config_path = tmp_path / "config.yml"
    _write_config(config_path, mqtt_host="localhost")
    app = MqttAlertsApp.from_config_file(str(config_path))
    app._client = SimpleNamespace(  # pylint: disable=protected-access
        is_connected=lambda: True,
        subscribe=lambda _topic: None,
        unsubscribe=lambda _topic: None,
    )

    _write_config(config_path, mqtt_host="broker.internal")

    app._reload_config_if_changed()  # pylint: disable=protected-access

    assert app.config.mqtt.host == "localhost"
    assert "restart required" in caplog.text
    app._state_store.close()  # pylint: disable=protected-access


def test_reload_config_keeps_previous_runtime_on_invalid_config(
    tmp_path: Path, caplog
) -> None:
    """Invalid config edits should be logged and ignored without replacing the live config."""
    config_path = tmp_path / "config.yml"
    _write_config(config_path, sensor_topic="measurements/freezer1")
    app = MqttAlertsApp.from_config_file(str(config_path))

    config_path.write_text("mqtt:\n  host: localhost\n", encoding="utf-8")

    app._reload_config_if_changed()  # pylint: disable=protected-access

    assert app._engine.subscribed_topics() == [
        "measurements/freezer1"
    ]  # pylint: disable=protected-access
    assert "config reload failed" in caplog.text
    app._state_store.close()  # pylint: disable=protected-access


def test_poll_notification_backends_acknowledges_active_alert(tmp_path: Path) -> None:
    """Telegram callback polling should update alert state and persist the acknowledgement."""
    state_store = SQLiteStateStore(str(tmp_path / "state.sqlite3"))
    engine = AlertEngine((_build_sensor(),))
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    engine.process_message(
        "measurements/A118636/27054",
        {"reading": 7.0},
        observed_at=start,
    )
    fired = engine.process_message(
        "measurements/A118636/27054",
        {"reading": 7.1},
        observed_at=start + timedelta(minutes=20),
    )
    alert_id = fired.notifications[0].alert_id
    app = MqttAlertsApp(
        config=_build_config(str(tmp_path / "state.sqlite3")),
        state_store=state_store,
        dispatcher=NotificationDispatcher({}),
        engine=engine,
    )
    captured = {}

    class FakeBackend:
        backend_id = "main_telegram"

        def ready_to_poll(self, _now):
            return True

        def poll_interactions(self, _now):
            return [
                SimpleNamespace(
                    alert_id=alert_id,
                    acknowledged_by="@alice",
                    callback_query_id="callback-1",
                    chat_id="-100123",
                    message_id=10,
                    message_text="Freezer alert",
                )
            ]

        def finalize_acknowledgement(self, interaction, result):
            captured["interaction"] = interaction
            captured["result"] = result

    app._telegram_backends = lambda: [FakeBackend()]  # pylint: disable=protected-access

    app._poll_notification_backends()  # pylint: disable=protected-access

    reloaded = state_store.load_states()
    state = reloaded[_rule_key()]
    assert state.current_alert is not None
    assert state.current_alert.state == "acknowledged"
    assert state.current_alert.acknowledged_by == "@alice"
    assert captured["result"].status == "acknowledged"
    state_store.close()


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


def _write_config(
    config_path: Path,
    *,
    sensor_topic: str = "measurements/A118636/27054",
    mqtt_host: str = "localhost",
) -> None:
    config_path.write_text(
        f"""
mqtt:
  host: {mqtt_host}
  port: 1883

state:
  database: {config_path.parent / "state.sqlite3"}

notifications:
  backends:
    - id: main_ntfy
      type: ntfy
      server: https://ntfy.sh
      topic: topic

sensors:
  - id: kitchen_fridge
    name: Kitchen fridge
    topic: {sensor_topic}
    value_field: reading
    rules:
      - id: high_warn
        direction: above
        threshold: 6.0
        for: 20m
        severity: warning
        backend: main_ntfy
""",
        encoding="utf-8",
    )


def _rule_key():
    return RuleKey(sensor_id="kitchen_fridge", rule_id="high_warn")
