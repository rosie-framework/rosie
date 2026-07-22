"""``rosie drivers`` — driver / base inventory."""

from __future__ import annotations

import argparse


def cmd_drivers_list(args: argparse.Namespace) -> int:
    from rosie.robot_config import format_drivers_list, load_registry

    print(
        format_drivers_list(
            load_registry(),
            category=args.category,
            platform=args.platform,
        ),
        end="",
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_drivers = sub.add_parser("drivers", help="list Rosie driver / base inventory")
    drivers_sub = p_drivers.add_subparsers(dest="drivers_command")
    p_dlist = drivers_sub.add_parser("list", help="print supported and planned drivers")
    p_dlist.add_argument(
        "--category",
        default=None,
        help="filter: motors, encoders, imu, camera, base, network",
    )
    p_dlist.add_argument(
        "--platform",
        default=None,
        choices=("mcu", "linux"),
        help="filter by platform (mcu or linux)",
    )
    p_dlist.set_defaults(func=cmd_drivers_list)
