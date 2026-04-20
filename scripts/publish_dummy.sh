#!/bin/sh

set -eu

HOST="localhost"
TOPIC="measurements/dummy/123456"
SENSOR_ID="123456"
BATTERY="2.8"
TYPE="FT10"
RSL="-70"
INTERVAL="10"
COUNT="1"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/publish_dummy.sh <value> [options]

Options:
  --host <host>         MQTT host (default: localhost)
  --topic <topic>       MQTT topic (default: measurements/dummy/123456)
  --sensor-id <id>      Sensor id in JSON payload (default: 123456)
  --interval <seconds>  Seconds between publishes (default: 10)
  --count <count>       Number of messages to send (default: 1)
  --loop                Publish continuously until interrupted
  --battery <value>     Battery value in JSON payload (default: 2.8)
  --type <value>        Sensor type in JSON payload (default: FT10)
  --rsl <value>         RSL value in JSON payload (default: -70)

Examples:
  ./scripts/publish_dummy.sh -35
  ./scripts/publish_dummy.sh -25 --count 30 --interval 10
  ./scripts/publish_dummy.sh -25 --loop --interval 10
EOF
}

if [ "$#" -lt 1 ]; then
    usage
    exit 1
fi

VALUE="$1"
shift

LOOP="false"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --topic)
            TOPIC="$2"
            shift 2
            ;;
        --sensor-id)
            SENSOR_ID="$2"
            shift 2
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --count)
            COUNT="$2"
            shift 2
            ;;
        --loop)
            LOOP="true"
            shift
            ;;
        --battery)
            BATTERY="$2"
            shift 2
            ;;
        --type)
            TYPE="$2"
            shift 2
            ;;
        --rsl)
            RSL="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

publish_once() {
    TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    PAYLOAD="$(printf '{"battery": %s, "type": "%s", "rsl": %s, "id": "%s", "reading": %s, "timestamp": "%s"}' \
        "$BATTERY" "$TYPE" "$RSL" "$SENSOR_ID" "$VALUE" "$TIMESTAMP")"
    echo "Publishing to $TOPIC: $PAYLOAD"
    mosquitto_pub -h "$HOST" -t "$TOPIC" -m "$PAYLOAD"
}

if [ "$LOOP" = "true" ]; then
    while true; do
        publish_once
        sleep "$INTERVAL"
    done
fi

CURRENT=0
while [ "$CURRENT" -lt "$COUNT" ]; do
    publish_once
    CURRENT=$((CURRENT + 1))
    if [ "$CURRENT" -lt "$COUNT" ]; then
        sleep "$INTERVAL"
    fi
done
