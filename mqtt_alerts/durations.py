"""Helpers for parsing human-friendly duration strings."""

from __future__ import annotations

from datetime import timedelta
import re


_DURATION_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[smhd])$")
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def parse_duration(text: str) -> timedelta:
    """Parse a compact duration such as ``15m`` or ``2h``."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("duration must be a non-empty string")

    match = _DURATION_PATTERN.fullmatch(text.strip().lower())
    if match is None:
        raise ValueError(f"unsupported duration format: {text!r}")

    value = int(match.group("value"))
    unit = match.group("unit")
    return timedelta(seconds=value * _UNIT_SECONDS[unit])


def format_duration(value: timedelta) -> str:
    """Render a timedelta in the compact format used by the config file."""
    total_seconds = int(value.total_seconds())
    for suffix, divisor in (("d", 86400), ("h", 3600), ("m", 60)):
        if total_seconds % divisor == 0 and total_seconds >= divisor:
            return f"{total_seconds // divisor}{suffix}"
    return f"{total_seconds}s"
