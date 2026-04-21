# Development

## Local Setup

```sh
uv sync --group dev
```

## Common Commands

```sh
make install
make install-hooks
make check-commits
make verify
make lint
make test
make build
```

## Commit Message Checks

This project uses semantic-release with Conventional Commits. Install the
repository-managed Git hooks once per clone:

```sh
make install-hooks
```

The hook validates the final commit message at the `commit-msg` stage. CI runs
the same checker for pull request titles and non-merge commit subjects so
release-relevant commit messages stay compatible with semantic-release.

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
