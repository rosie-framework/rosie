"""``rosie teleop`` — WASD keyboard teleop."""

from __future__ import annotations

import argparse
import os


def cmd_teleop(args: argparse.Namespace) -> int:
    from rosie.tools.teleop_twist import run_teleop

    run_teleop(
        robot=args.robot,
        fleet=args.fleet,
        v_fwd=args.v_fwd,
        v_turn=args.v_turn,
        pub_hz=args.hz,
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_tele = sub.add_parser("teleop", help="WASD keyboard teleop → <robot>/cmd_vel")
    p_tele.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT", "robot"),
        help="robot id (default: ROSIE_ROBOT or robot)",
    )
    p_tele.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="optional fleet id (default: ROSIE_FLEET)",
    )
    p_tele.add_argument("--v-fwd", type=float, default=0.25, help="forward speed m/s")
    p_tele.add_argument("--v-turn", type=float, default=1.0, help="yaw rate rad/s")
    p_tele.add_argument("--hz", type=float, default=10.0, help="publish rate")
    p_tele.set_defaults(func=cmd_teleop)
