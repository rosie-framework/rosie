"""``rosie drive`` — interactive MobileRobot REPL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _parse_waypoints(cmd: str) -> list[tuple[float, float]] | None:
    parts = cmd.split()
    if len(parts) < 2 or len(parts) % 2 != 0:
        return None
    waypoints: list[tuple[float, float]] = []
    for i in range(0, len(parts), 2):
        try:
            waypoints.append((float(parts[i]), float(parts[i + 1])))
        except ValueError:
            return None
    return waypoints


def cmd_drive(args: argparse.Namespace) -> int:
    """Interactive REPL over MobileRobot helpers (drive_route, teleop, camera, …)."""
    from rosie.mobile_robot import MobileRobot
    from rosie.robot_config import find_robot_yaml

    config = args.config
    if not config:
        found = find_robot_yaml(Path(args.dir))
        config = str(found) if found else None

    print("Opening Rosie session (zenohd / `rosie router` must be running)...")
    try:
        bot = MobileRobot(
            robot=args.robot,
            fleet=args.fleet,
            connect=args.connect,
            name="drive",
            config_path=config,
            secure=bool(getattr(args, "secure", False)),
        )
    except Exception as e:
        print(f"Could not open session: {e}", file=sys.stderr)
        return 1

    print(f"Robot id: {bot.robot_id}")
    p = bot.wait_for_pose(3.0)
    if p:
        print(
            f"Linked. pose x={p.get('x', 0):.3f} y={p.get('y', 0):.3f} "
            f"mode={p.get('mode', '?')}"
        )
        try:
            bot.zero()
            print("Pose zero requested.")
        except Exception as e:
            print(f"  warning: zero failed: {e}")
    else:
        print("No pose yet — CLI is up, but the robot is not publishing.")

    print("Commands: x y [x y ...] | teleop | snap | cam | zero | imu | stop | quit")
    while True:
        try:
            cmd = input("target> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        low = cmd.lower()
        if low in ("quit", "exit", "q"):
            break
        if low == "stop":
            bot.stop()
            print("  STOP sent.")
            continue
        if low == "zero":
            bot.zero()
            print("  pose zeroed.")
            continue
        if low == "imu":
            bot.set_heading_source(None)
            print("  heading_source toggle sent.")
            continue
        if low == "snap":
            try:
                bot.snap()
            except Exception as e:
                print(f"  snap failed: {e}")
            continue
        if low == "cam":
            try:
                bot.camera_live()
            except Exception as e:
                print(f"  cam failed: {e}")
            continue
        if low == "teleop":
            try:
                bot.teleop()
            except Exception as e:
                print(f"  teleop failed: {e}")
            continue
        waypoints = _parse_waypoints(cmd)
        if waypoints is None:
            print("  enter pairs 'x y [x y ...]', or teleop / snap / cam / stop / quit")
            continue
        try:
            bot.drive_route(waypoints)
        except KeyboardInterrupt:
            pass

    bot.close()
    print("Bye.")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_drive = sub.add_parser(
        "drive",
        help="interactive REPL over MobileRobot nav helpers for a MobileBase robot",
    )
    p_drive.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT"),
        help="robot id (default: robot.yaml / ROSIE_ROBOT)",
    )
    p_drive.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="fleet id (default: robot.yaml / ROSIE_FLEET)",
    )
    p_drive.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p_drive.add_argument(
        "--secure",
        action="store_true",
        help="authenticate to a secure router (usrpwd / host secret)",
    )
    p_drive.add_argument(
        "--config",
        default=None,
        help="path to robot.yaml (default: ./robot.yaml if present)",
    )
    p_drive.add_argument(
        "--dir",
        default=".",
        help="directory to search for robot.yaml (default: cwd)",
    )
    p_drive.set_defaults(func=cmd_drive)
