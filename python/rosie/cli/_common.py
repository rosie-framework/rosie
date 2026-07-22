"""Shared CLI argparse helpers and small utilities."""

from __future__ import annotations

import argparse
import os
import socket


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


def local_ipv4s() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips
