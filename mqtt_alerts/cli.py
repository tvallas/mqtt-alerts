"""CLI entrypoint for mqtt-alerts."""

from __future__ import annotations

from argparse import ArgumentParser
from importlib.metadata import PackageNotFoundError, version
import logging
import os
import sys

from mqtt_alerts.config import ConfigError
from mqtt_alerts.runtime import ApplicationError, run_application


def create_parser() -> ArgumentParser:
    """Build the command line parser."""
    parser = ArgumentParser(
        description=(
            "Subscribe to MQTT topics, evaluate alert rules, and send notifications."
        )
    )
    parser.add_argument(
        "--config",
        "-c",
        default=os.environ.get("MQTT_ALERTS_CONFIG_FILE"),
        help="Path to YAML config file (ENV: MQTT_ALERTS_CONFIG_FILE)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--debug",
        "-d",
        default=_env_flag("MQTT_ALERTS_DEBUG", False),
        action="store_true",
        help="Enable debug logging (ENV: MQTT_ALERTS_DEBUG)",
    )
    group.add_argument(
        "--quiet",
        "-q",
        default=_env_flag("MQTT_ALERTS_QUIET", False),
        action="store_true",
        help="Only log warnings and errors (ENV: MQTT_ALERTS_QUIET)",
    )
    group.add_argument(
        "--version",
        "-v",
        default=False,
        action="store_true",
        help="Print the mqtt-alerts version and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(_project_version())
        return 0

    if not args.config:
        parser.error("--config is required unless MQTT_ALERTS_CONFIG_FILE is set")

    configure_logging(args.debug, args.quiet)

    try:
        run_application(args.config)
    except (ApplicationError, ConfigError) as error:
        logging.getLogger(__name__).error("%s", error)
        return 1

    return 0


def configure_logging(debug: bool, quiet: bool) -> None:
    """Configure the root logger for the selected verbosity mode."""
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        return
    if quiet:
        logging.basicConfig(level=logging.WARNING)
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
    sys.tracebacklimit = 0


def _project_version() -> str:
    try:
        return version("mqtt-alerts")
    except PackageNotFoundError:
        return "0.0.0"


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes", "on"}
