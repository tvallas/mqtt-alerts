"""Tests for duration parsing and formatting helpers."""

from __future__ import annotations

from datetime import timedelta

from mqtt_alerts.durations import format_duration


def test_format_duration_keeps_exact_minutes_compact() -> None:
    """Exact minute values should stay short and familiar."""
    assert format_duration(timedelta(minutes=15)) == "15m"


def test_format_duration_uses_mixed_units_for_non_exact_values() -> None:
    """Non-exact durations should be rendered with mixed units instead of raw seconds."""
    assert format_duration(timedelta(seconds=127)) == "2m 7s"
    assert format_duration(timedelta(seconds=3661)) == "1h 1m 1s"
    assert format_duration(timedelta(days=1, hours=2, minutes=3, seconds=4)) == "1d 2h 3m 4s"
