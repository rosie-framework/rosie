"""``rosie agent`` — ROS 2 ↔ Rosie bridge on the robot."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rosie.agent.config import KNOWN_PROFILES, default_config_path


def _load_cfg(args: argparse.Namespace):
    from rosie.agent.config import load_agent_config

    path = args.config
    if path is None and default_config_path().is_file():
        path = default_config_path()
    return load_agent_config(
        path,
        robot=args.robot,
        fleet=args.fleet,
        connect=args.connect,
        profile=args.profile,
        cmd_vel=getattr(args, "cmd_vel", None),
        odom=getattr(args, "odom", None),
    )


def cmd_agent_run(args: argparse.Namespace) -> int:
    from rosie.agent.runner import run_agent

    try:
        cfg = _load_cfg(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return run_agent(cfg)


def cmd_agent_init(args: argparse.Namespace) -> int:
    from rosie.agent.runner import init_agent

    try:
        path = init_agent(
            path=args.config or default_config_path(),
            robot=args.robot,
            fleet=args.fleet,
            connect=args.connect,
            profile=args.profile,
            force=args.force,
        )
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {path}")
    print("Next: source ROS 2, then `rosie agent run` (or `rosie agent install`).")
    return 0


def cmd_agent_install(args: argparse.Namespace) -> int:
    from rosie.agent.runner import install_agent

    try:
        unit = install_agent(
            config_path=args.config or default_config_path(),
            working_directory=args.workdir,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {unit}")
    print("Enable and start (user systemd):")
    print("  systemctl --user daemon-reload")
    print("  systemctl --user enable --now rosie-agent.service")
    print("Logs: journalctl --user -u rosie-agent -f")
    return 0


def cmd_agent_doctor(args: argparse.Namespace) -> int:
    from rosie.agent.runner import doctor

    try:
        cfg = _load_cfg(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return doctor(cfg)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config",
        default=None,
        help=f"path to agent.yaml (default: ./{default_config_path().name} if present)",
    )
    p.add_argument(
        "--robot",
        default=None,
        help="robot id (default: agent.yaml / ROSIE_ROBOT / robot)",
    )
    p.add_argument(
        "--fleet",
        default=None,
        help="fleet id (default: agent.yaml / ROSIE_FLEET)",
    )
    p.add_argument(
        "--connect",
        default=None,
        help="Zenoh router (default: agent.yaml / ROSIE_CONNECT / local)",
    )
    p.add_argument(
        "--profile",
        default=None,
        help=f"ROS topic profile ({', '.join(KNOWN_PROFILES)})",
    )


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "agent",
        help="ROS 2 ↔ Rosie bridge (run on the robot)",
    )
    agent_sub = p.add_subparsers(dest="agent_command")

    p_run = agent_sub.add_parser("run", help="run the ROS 2 bridge (foreground)")
    _add_common(p_run)
    p_run.add_argument("--cmd-vel", default=None, help="ROS cmd_vel topic override")
    p_run.add_argument("--odom", default=None, help="ROS odometry topic override")
    p_run.set_defaults(func=cmd_agent_run)

    p_init = agent_sub.add_parser("init", help="write agent.yaml")
    _add_common(p_init)
    p_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing agent.yaml",
    )
    p_init.set_defaults(func=cmd_agent_init)

    p_inst = agent_sub.add_parser(
        "install",
        help="write systemd --user unit for the agent",
    )
    p_inst.add_argument(
        "--config",
        default=None,
        help="path to agent.yaml (default: ./agent.yaml)",
    )
    p_inst.add_argument(
        "--workdir",
        default=None,
        help="WorkingDirectory for the unit (default: config directory)",
    )
    p_inst.set_defaults(func=cmd_agent_install)

    p_doc = agent_sub.add_parser("doctor", help="check config, rclpy, and router")
    _add_common(p_doc)
    p_doc.add_argument("--cmd-vel", default=None, help="ROS cmd_vel topic override")
    p_doc.add_argument("--odom", default=None, help="ROS odometry topic override")
    p_doc.set_defaults(func=cmd_agent_doctor)
