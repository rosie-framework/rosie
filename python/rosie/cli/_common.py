"""Shared CLI argparse helpers and small utilities."""

from __future__ import annotations

import argparse
import os

from rosie.netinfo import local_ipv4s

__all__ = ["add_fleet_common", "resolve_fleet_id", "local_ipv4s"]


def add_fleet_common(
    p: argparse.ArgumentParser, *, fleet_required: bool = False
) -> None:
    p.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        required=fleet_required,
        help="fleet id (default: ROSIE_FLEET)",
    )
    p.add_argument(
        "--connect",
        default=None,
        help="override ROSIE_CONNECT",
    )


def resolve_fleet_id(args: argparse.Namespace) -> str:
    fleet = getattr(args, "fleet", None) or os.environ.get("ROSIE_FLEET")
    if not fleet:
        raise SystemExit("error: --fleet or ROSIE_FLEET is required")
    return fleet
