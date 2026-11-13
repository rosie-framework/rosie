"""``rosie teleop`` — WASD keyboard teleop."""

from __future__ import annotations

import argparse
import os
import sys


def cmd_teleop(args: argparse.Namespace) -> int:
    from rosie.tools.teleop_twist import run_teleop

    if not args.fleet:
        print("error: --fleet or ROSIE_FLEET is required", file=sys.stderr)
        return 2

    run_teleop(
        robot=args.robot,
        fleet=args.fleet,
        secure=bool(getattr(args, "secure", False)),
        v_fwd=args.v_fwd,
        v_turn=args.v_turn,
        pub_hz=args.hz,
        profile=args.profile,
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_tele = sub.add_parser("teleop", help="WASD keyboard teleop on the profile velocity topic")
    p_tele.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT", "robot"),
        help="robot id (default: ROSIE_ROBOT or robot)",
    )
    p_tele.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="fleet id (required; default: ROSIE_FLEET)",
    )
    p_tele.add_argument(
        "--secure",
        action="store_true",
        help="authenticate to a secure router (usrpwd / host secret)",
    )
    p_tele.add_argument("--v-fwd", type=float, default=0.25, help="forward speed m/s")
    p_tele.add_argument("--v-turn", type=float, default=1.0, help="yaw rate rad/s")
    p_tele.add_argument("--hz", type=float, default=10.0, help="publish rate")
    p_tele.add_argument(
        "--profile",
        default="default_ros2",
        help="robot profile (default: default_ros2)",
    )
    p_tele.set_defaults(func=cmd_teleop)
