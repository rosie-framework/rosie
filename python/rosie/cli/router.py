"""``rosie router`` — run zenohd."""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib import resources
from pathlib import Path

from rosie.cli._common import local_ipv4s


def default_config_path() -> Path:
    """Packaged zenoh.json5, with fallback to repo tools/ for editable checkouts."""
    try:
        traj = resources.files("rosie").joinpath("data/zenoh.json5")
        with resources.as_file(traj) as p:
            if p.is_file():
                return Path(p)
    except Exception:
        pass
    # this file: python/rosie/cli/router.py → parents[3] = repo
    repo = Path(__file__).resolve().parents[3]
    candidate = repo / "tools" / "zenoh.json5"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        "Could not find zenoh.json5 package data. Reinstall Rosie or pass --config."
    )


def cmd_router(args: argparse.Namespace) -> int:
    from rosie.bootstrap import find_zenohd

    zenohd = find_zenohd(fetch=not args.no_fetch, force=False, quiet=False)
    config = Path(args.config).expanduser() if args.config else default_config_path()
    if not config.is_file():
        print(f"error: config not found: {config}", file=sys.stderr)
        return 1

    cmd = [str(zenohd), "-c", str(config)]
    if args.listen:
        cmd.extend(["--listen", args.listen])
    if args.connect:
        cmd.extend(["--connect", args.connect])
    if args.extra:
        cmd.extend(args.extra)

    print(f"Starting zenohd ({zenohd})")
    print(f"  config: {config}")
    print("  host tools default to tcp/127.0.0.1:7447 (no ROSIE_CONNECT needed)")
    lan = local_ipv4s()
    if lan:
        print("  put one of these in robot.yaml network.connect (MCU → this laptop):")
        for ip in lan:
            print(f"    tcp/{ip}:7447")
    else:
        print(
            "  (could not detect LAN IP — set robot.yaml network.connect to "
            "tcp/<this-laptop-ip>:7447)"
        )
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


def register(sub: argparse._SubParsersAction) -> None:
    p_router = sub.add_parser("router", help="run the Zenoh router (zenohd)")
    p_router.add_argument(
        "--config",
        default=None,
        help="zenohd JSON5 config (default: packaged listen-all config)",
    )
    p_router.add_argument(
        "--listen",
        default=None,
        help="extra --listen endpoint passed to zenohd",
    )
    p_router.add_argument(
        "--connect",
        default=None,
        help="extra --connect endpoint passed to zenohd",
    )
    p_router.add_argument(
        "--no-fetch",
        action="store_true",
        help="do not download zenohd if missing",
    )
    p_router.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="extra args after -- passed to zenohd",
    )
    p_router.set_defaults(func=cmd_router)
