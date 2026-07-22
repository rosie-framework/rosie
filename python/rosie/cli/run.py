"""``rosie run`` — Linux-native mobile base from robot.yaml."""

from __future__ import annotations

import argparse
import os
import sys


def cmd_run(args: argparse.Namespace) -> int:
    from rosie.run.runtime import run_from_config
    from rosie.robot_config import load_robot_config

    try:
        cfg = load_robot_config(args.config)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    robot = args.robot
    fleet = args.fleet
    connect = args.connect
    try:
        return run_from_config(
            cfg,
            robot=robot,
            fleet=fleet,
            connect=connect,
            dry_run=args.dry_run,
        )
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run",
        help="run Linux-native mobile base from robot.yaml (platform: linux)",
    )
    p.add_argument(
        "--config",
        required=True,
        help="path to robot.yaml (must set platform: linux)",
    )
    p.add_argument(
        "--robot",
        default=None,
        help="override robot id (default: robot.yaml / ROSIE_ROBOT)",
    )
    p.add_argument(
        "--fleet",
        default=None,
        help="override fleet id (default: robot.yaml / ROSIE_FLEET)",
    )
    p.add_argument(
        "--connect",
        default=None,
        help="override Zenoh connect (default: robot.yaml / ROSIE_CONNECT)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="load and validate config; print drivers; do not open hardware",
    )
    p.set_defaults(func=cmd_run)
