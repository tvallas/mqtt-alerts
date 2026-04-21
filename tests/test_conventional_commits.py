"""Tests for Conventional Commit validation helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def test_conventional_commit_subjects_are_accepted() -> None:
    """Valid semantic-release commit subjects should pass."""
    checker = _load_checker()
    failures: list[str] = []

    for subject in (
        "fix: handle MQTT reconnect errors",
        "docs(readme): clarify Docker setup",
        "feat(alerts)!: change reminder acknowledgement flow",
        "chore(release): 0.4.1",
    ):
        checker._check_subject(subject, "test", allow_merge=False, failures=failures)

    assert not failures


def test_invalid_commit_subject_is_rejected() -> None:
    """Non-conventional subjects should fail validation."""
    checker = _load_checker()
    failures: list[str] = []

    checker._check_subject("misc fixes", "test", allow_merge=False, failures=failures)

    assert failures == ["test: 'misc fixes'"]


def test_commit_message_subject_ignores_comment_lines() -> None:
    """Git commit templates can include comments after the subject."""
    checker = _load_checker()

    assert (
        checker._first_subject_line("fix: validate commits\n\n# Please enter a message")
        == "fix: validate commits"
    )


def _load_checker() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "check_conventional_commits.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_conventional_commits", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
