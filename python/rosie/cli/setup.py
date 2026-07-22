"""``rosie version`` and ``rosie setup``."""

from __future__ import annotations

import argparse

from rosie import __version__


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"rosie {__version__}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from rosie.bootstrap import download_zenohd

    download_zenohd(force=args.force, quiet=False)
    print("Host setup complete (zenohd cached).")
    print("Tip: for MCU projects, run `rosie mcu setup` in the robot directory.")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_ver = sub.add_parser("version", help="print Rosie version")
    p_ver.set_defaults(func=cmd_version)

    p_setup = sub.add_parser(
        "setup",
        help="download/cache zenohd while online (before joining an offline demo AP)",
    )
    p_setup.add_argument(
        "--force", action="store_true", help="re-download even if cached"
    )
    p_setup.set_defaults(func=cmd_setup)
