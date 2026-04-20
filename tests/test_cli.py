"""Tests for the CLI module."""

from __future__ import annotations

from mqtt_alerts import cli
from mqtt_alerts.runtime import ApplicationError


def test_main_runs_application_with_config_path(monkeypatch) -> None:
    """The CLI forwards the parsed config path into the runtime helper."""
    captured = {}

    def fake_run_application(config_path: str) -> None:
        captured["config_path"] = config_path

    monkeypatch.setattr(cli, "run_application", fake_run_application)

    exit_code = cli.main(["--config", "sample_config.yml"])

    assert exit_code == 0
    assert captured["config_path"] == "sample_config.yml"


def test_main_returns_non_zero_on_application_error(monkeypatch) -> None:
    """Fatal startup errors become a non-zero exit status."""
    monkeypatch.setattr(
        cli,
        "run_application",
        lambda _config_path: (_ for _ in ()).throw(ApplicationError("startup failed")),
    )

    exit_code = cli.main(["--config", "sample_config.yml"])

    assert exit_code == 1
