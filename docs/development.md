# Development

## Local Setup

```sh
uv sync --group dev
```

## Common Commands

```sh
make install
make lint
make test
make build
```

## Project Structure

- `mqtt_alerts.config`: YAML loading and validation
- `mqtt_alerts.engine`: rule evaluation and lifecycle transitions
- `mqtt_alerts.persistence`: SQLite state and alert instances
- `mqtt_alerts.notifications`: backend delivery and acknowledgement polling
- `mqtt_alerts.runtime`: MQTT subscription loop and runtime wiring
- `mqtt_alerts.cli`: CLI entrypoint

## CI and Release

- CI checks lint, tests, and package build
- Docker workflow performs PR build smoke test
- Trivy workflow scans filesystem and image vulnerabilities
- Semantic release publishes GitHub/PyPI releases and then Docker images
