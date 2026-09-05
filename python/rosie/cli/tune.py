"""``rosie tune`` — live velocity PID tuning CLI."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rosie.tools.tune import (
    latest_control,
    run_tune_interactive,
    save_velocity_gains_to_yaml,
)


def cmd_tune(args: argparse.Namespace) -> int:
    """Entry for ``rosie tune`` / ``rosie tune set`` / ``rosie tune save``."""
    from rosie.mobile_robot import MobileRobot
    from rosie.robot_config import find_robot_yaml

    config = getattr(args, "config", None)
    if not config:
        found = find_robot_yaml(Path(getattr(args, "dir", ".") or "."))
        config = str(found) if found else None

    sub = getattr(args, "tune_command", None) or "interactive"

    if sub == "save":
        if not config:
            print("error: --config robot.yaml required for save", file=sys.stderr)
            return 2
        if args.kp is None and args.ki is None and args.kd is None:
            bot = MobileRobot(
                robot=args.robot,
                fleet=args.fleet,
                connect=args.connect,
                name="tune",
                config_path=config,
            )
            msg = latest_control(bot)
            if not msg or "kp" not in msg:
                print("error: no control telemetry from robot", file=sys.stderr)
                return 1
            out = save_velocity_gains_to_yaml(
                config,
                kp=float(msg["kp"]),
                ki=float(msg.get("ki", 0)),
                kd=float(msg.get("kd", 0)),
                i_clamp=float(msg.get("i_clamp", 0.5)),
            )
        else:
            out = save_velocity_gains_to_yaml(
                config,
                kp=float(args.kp if args.kp is not None else 0.0),
                ki=float(args.ki if args.ki is not None else 0.0),
                kd=float(args.kd if args.kd is not None else 0.0),
                i_clamp=float(args.i_clamp if args.i_clamp is not None else 0.5),
            )
        print(f"Wrote {out}")
        platform = "mcu"
        try:
            from rosie.robot_config import load_robot_config

            platform = load_robot_config(config).platform
        except Exception:
            pass
        if platform == "linux":
            print("Restart `rosie run` to load saved defaults from YAML")
        else:
            print("Reflash to bake defaults: rosie mcu flash")
        return 0

    bot = MobileRobot(
        robot=args.robot,
        fleet=args.fleet,
        connect=args.connect,
        name="tune",
        config_path=config,
    )

    if sub == "set":
        kwargs = {}
        if args.kp is not None:
            kwargs["kp"] = args.kp
        if args.ki is not None:
            kwargs["ki"] = args.ki
        if args.kd is not None:
            kwargs["kd"] = args.kd
        if args.i_clamp is not None:
            kwargs["i_clamp"] = args.i_clamp
        if not kwargs:
            print(
                "error: pass at least one of --kp/--ki/--kd/--i-clamp",
                file=sys.stderr,
            )
            return 2
        bot.set_gains(**kwargs)
        print(f"set_gains {kwargs}")
        time.sleep(0.3)
        msg = latest_control(bot)
        if msg:
            print(
                f"robot: kp={msg.get('kp')} ki={msg.get('ki')} "
                f"kd={msg.get('kd')} i_clamp={msg.get('i_clamp')}"
            )
        return 0

    return run_tune_interactive(bot, config_path=config)


def _tune_common(
    p: argparse.ArgumentParser, *, config_required: bool = False
) -> None:
    p.add_argument("--robot", default=None, help="robot id (or from --config)")
    p.add_argument("--fleet", default=None, help="fleet id (default: robot.yaml / ROSIE_FLEET)")
    p.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p.add_argument(
        "--config",
        default=None,
        required=config_required,
        help="robot.yaml (defaults + save target)",
    )
    p.add_argument(
        "--dir",
        default=".",
        help="project dir to search for robot.yaml when --config omitted",
    )
    p.add_argument("--kp", type=float, default=None)
    p.add_argument("--ki", type=float, default=None)
    p.add_argument("--kd", type=float, default=None)
    p.add_argument("--i-clamp", dest="i_clamp", type=float, default=None)
    p.set_defaults(func=cmd_tune)


def register(sub: argparse._SubParsersAction) -> None:
    p_tune = sub.add_parser(
        "tune",
        help="live-tune onboard velocity PID gains (interactive / set / save)",
    )
    tune_sub = p_tune.add_subparsers(dest="tune_command")

    _tune_common(p_tune)
    p_tset = tune_sub.add_parser("set", help="one-shot set_gains to the robot")
    _tune_common(p_tset)
    p_tsave = tune_sub.add_parser(
        "save",
        help="write control.velocity into robot.yaml (from flags or live robot)",
    )
    _tune_common(p_tsave, config_required=True)
