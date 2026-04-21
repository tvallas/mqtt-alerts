# Deployment

## CLI

```sh
mqtt-alerts --config /path/to/config.yml
```

Flags:

- `--config` / `-c`
- `--debug` / `-d`
- `--quiet` / `-q`
- `--version` / `-v`

Environment variables:

- `MQTT_ALERTS_CONFIG_FILE`
- `MQTT_ALERTS_DEBUG`
- `MQTT_ALERTS_QUIET`

## Docker

```sh
docker pull tvallas/mqtt-alerts:latest

docker run --rm \
  -v "$(pwd)/sample_config.yml:/config/config.yml:ro" \
  -v "$(pwd)/state:/state" \
  tvallas/mqtt-alerts:latest \
  --config /config/config.yml
```

## Docker Compose

The repository includes both `docker-compose.yml` and `docker-compose.local.yml`.

```sh
docker compose up -d
```

## Reload Behavior

The process polls the config file and applies sensor, rule, backend, and topic updates automatically.

Restart is still required when changing:

- MQTT connection settings (`mqtt.host`, `mqtt.port`)
- SQLite path (`state.database`)
