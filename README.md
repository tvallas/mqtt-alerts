# mqtt-alerts

[![CI](https://github.com/tvallas/mqtt-alerts/actions/workflows/ci.yml/badge.svg)](https://github.com/tvallas/mqtt-alerts/actions/workflows/ci.yml)
[![Docker](https://github.com/tvallas/mqtt-alerts/actions/workflows/docker.yml/badge.svg)](https://github.com/tvallas/mqtt-alerts/actions/workflows/docker.yml)
[![Trivy](https://github.com/tvallas/mqtt-alerts/actions/workflows/trivy.yml/badge.svg)](https://github.com/tvallas/mqtt-alerts/actions/workflows/trivy.yml)
[![PyPI version](https://img.shields.io/pypi/v/mqtt-alerts.svg)](https://pypi.org/project/mqtt-alerts/)
[![Python 3.10-3.13](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/tvallas/mqtt-alerts/blob/master/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<p align="center">
  <img src="docs/assets/mqtt-alerts.png" alt="mqtt-alerts logo" width="220" />
</p>

`mqtt-alerts` is a general-purpose MQTT alerting service. It subscribes to MQTT topics, evaluates threshold rules with hold times and hysteresis, persists alert state, and sends notifications through pluggable backends.

It works with `mtr2mqtt`, but it is not tied to `mtr2mqtt`. Any publisher that sends JSON payloads to MQTT can use this service.

## Key Features

- Multiple independent rules per sensor topic
- Rule hold durations (`for`) and hysteresis support
- Persistent alert lifecycle: `pending`, `firing`, `acknowledged`, `resolved`
- SQLite-backed state and restart-safe acknowledgement tracking
- Pluggable notification backends: `telegram`, `ntfy`, `pushover`
- Automatic recovery notifications
- Outbound-only acknowledgement polling (no public webhook required)

## Supported Backends

- `telegram`: push notifications with acknowledgement buttons (polled via Bot API)
- `ntfy`: outbound push notifications
- `pushover`: push notifications with emergency receipt acknowledgement support

## Documentation

- [Documentation index](docs/README.md)
- [Configuration guide](docs/configuration.md)
- [Notification backends](docs/backends.md)
- [Examples](docs/examples.md)
- [Deployment](docs/deployment.md)
- [Development](docs/development.md)

## Quick Start

Install:

```sh
pip install mqtt-alerts
```

Run:

```sh
mqtt-alerts --config sample_config.yml
```

Container:

```sh
docker run --rm \
  -v "$(pwd)/sample_config.yml:/config/config.yml:ro" \
  -v "$(pwd)/state:/state" \
  tvallas/mqtt-alerts:latest \
  --config /config/config.yml
```
