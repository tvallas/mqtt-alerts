FROM python:3.14-alpine AS builder

WORKDIR /src

COPY pyproject.toml README.md /src/
COPY mqtt_alerts /src/mqtt_alerts

RUN python -m pip install --no-cache-dir --upgrade \
    pip \
    "setuptools>=80" \
    "wheel>=0.46.2" && \
    python -m pip wheel --no-cache-dir --wheel-dir /tmp/wheels /src

FROM python:3.14-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk upgrade --no-cache && \
    python -m pip install --no-cache-dir --upgrade "pip>=26.1"

COPY --from=builder /tmp/wheels /tmp/wheels

RUN python -m pip install --no-cache-dir --no-compile /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels

ENTRYPOINT ["mqtt-alerts"]
