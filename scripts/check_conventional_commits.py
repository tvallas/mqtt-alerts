#!/usr/bin/env python3
"""Validate Conventional Commit subjects for local hooks and CI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


CONVENTIONAL_SUBJECT = re.compile(
    r"^(?P<type>build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?P<scope>\([a-z0-9][a-z0-9._/-]*\))?"
    r"(?P<breaking>!)?: (?P<description>\S.*)$"
)


def main() -> int:
    args = _parse_args()
    failures: list[str] = []

    if args.commit_msg_file is not None:
        message = args.commit_msg_file.read_text(encoding="utf-8")
        _check_message(message, str(args.commit_msg_file), args.allow_merge, failures)

    for message in args.message:
        _check_subject(message, "provided message", args.allow_merge, failures)

    if args.rev_range is not None:
        for commit_hash, subject in _commit_subjects(args.rev_range):
            _check_subject(subject, commit_hash, allow_merge=True, failures=failures)

    if failures:
        print("Conventional Commit validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nExpected format: type(scope): description\n"
            "Allowed types: build, chore, ci, docs, feat, fix, perf, refactor, "
            "revert, style, test\n"
            "Examples: fix: handle MQTT reconnect errors, "
            "docs(readme): clarify Docker setup",
            file=sys.stderr,
        )
        return 1

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate commit subjects against Conventional Commits."
    )
    parser.add_argument(
        "--commit-msg-file",
        type=Path,
        help="Path to a git commit message file, as passed to commit-msg hooks.",
    )
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Validate a single message subject. May be provided multiple times.",
    )
    parser.add_argument(
        "--range",
        dest="rev_range",
        help="Validate non-merge commit subjects in a git revision range.",
    )
    parser.add_argument(
        "--allow-merge",
        action="store_true",
        help="Allow generated merge commit subjects such as 'Merge branch ...'.",
    )
    args = parser.parse_args()

    if (
        args.commit_msg_file is None
        and not args.message
        and args.rev_range is None
    ):
        parser.error("provide --commit-msg-file, --message, or --range")

    return args


def _check_message(
    message: str,
    source: str,
    allow_merge: bool,
    failures: list[str],
) -> None:
    subject = _first_subject_line(message)
    _check_subject(subject, source, allow_merge, failures)


def _check_subject(
    subject: str,
    source: str,
    allow_merge: bool,
    failures: list[str],
) -> None:
    if allow_merge and subject.startswith("Merge "):
        return
    if CONVENTIONAL_SUBJECT.fullmatch(subject):
        return
    failures.append(f"{source}: {subject!r}")


def _first_subject_line(message: str) -> str:
    for line in message.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _commit_subjects(rev_range: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        [
            "git",
            "log",
            "--no-merges",
            "--format=%H%x00%s",
            rev_range,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subjects: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        commit_hash, subject = line.split("\0", maxsplit=1)
        subjects.append((commit_hash, subject))
    return subjects


if __name__ == "__main__":
    raise SystemExit(main())
