from pathlib import Path


def test_runtime_stage_upgrades_pip_before_installing_app_wheel():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    runtime_stage = dockerfile.split("FROM python:3.14-alpine", maxsplit=2)[2]
    pip_upgrade = 'python -m pip install --no-cache-dir --upgrade "pip>=26.1"'
    wheel_install = "python -m pip install --no-cache-dir --no-compile /tmp/wheels/*.whl"

    assert pip_upgrade in runtime_stage
    assert runtime_stage.index(pip_upgrade) < runtime_stage.index(wheel_install)
