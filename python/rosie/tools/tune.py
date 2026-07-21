"""Live velocity-PID tuning helpers and `rosie tune` CLI support."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any


def save_velocity_gains_to_yaml(
    config_path: str | Path,
    *,
    kp: float,
    ki: float,
    kd: float,
    i_clamp: float = 0.5,
    type_: str = "pid",
) -> Path:
    """Write / update ``control.velocity`` in robot.yaml and return the path."""
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise ImportError(
            "PyYAML is required to save gains. Install with: pip install pyyaml"
        ) from e

    path = Path(config_path).expanduser().resolve()
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping at top level")

    control = data.setdefault("control", {})
    if not isinstance(control, dict):
        raise ValueError(f"{path}: control must be a mapping")
    control["velocity"] = {
        "type": type_,
        "kp": float(kp),
        "ki": float(ki),
        "kd": float(kd),
        "i_clamp": float(i_clamp),
    }
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _latest_control(bot: Any, timeout_s: float = 2.0) -> dict | None:
    box: dict[str, Any] = {"msg": None}
    lock = threading.Lock()

    def on_ctrl(msg: dict) -> None:
        with lock:
            box["msg"] = msg

    from rosie import topics

    bot.session.subscribe_json(topics.CONTROL, on_ctrl)
    bot.get_gains()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with lock:
            if box["msg"]:
                return dict(box["msg"])
        time.sleep(0.05)
    return None


def run_tune_interactive(bot: Any, config_path: str | Path | None = None) -> int:
    """Interactive gain editor. Keys: p/P k/K d/D, g=get, s=save, q=quit."""
    from rosie import topics

    control: dict = {}
    lock = threading.Lock()

    def on_ctrl(msg: dict) -> None:
        with lock:
            control.clear()
            control.update(msg)

    bot.session.subscribe_json(topics.CONTROL, on_ctrl)
    bot.get_gains()
    time.sleep(0.5)

    def snap() -> dict:
        with lock:
            return dict(control)

    print("Live velocity-PID tune (Ctrl-C or q to quit)")
    print("  commands: kp <v> | ki <v> | kd <v> | i_clamp <v>")
    print("            get | save | quit")
    print("  tip: start with a small kp (e.g. 0.2), add ki for steady-state")
    while True:
        c = snap()
        pose = bot.pose()
        tgt = c.get("target_vel") or []
        meas = c.get("meas_vel") or []
        err = ""
        if tgt and meas and len(tgt) == len(meas):
            errs = [float(t) - float(m) for t, m in zip(tgt, meas)]
            err = "  ".join(f"e{i}={e:+.3f}" for i, e in enumerate(errs))
        print(
            f"\r  kp={c.get('kp', '?'):>6} ki={c.get('ki', '?'):>6} kd={c.get('kd', '?'):>6}  "
            f"mode={c.get('mode', pose.get('mode', '?'))}  {err}   ",
            end="",
            flush=True,
        )
        try:
            line = input("\ntune> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit"):
            break
        if cmd == "get":
            bot.get_gains()
            continue
        if cmd == "save":
            path = config_path
            if not path:
                print("  no --config; pass --config robot.yaml to save")
                continue
            c = snap()
            if "kp" not in c:
                print("  no control telemetry yet — try 'get' first")
                continue
            out = save_velocity_gains_to_yaml(
                path,
                kp=float(c["kp"]),
                ki=float(c.get("ki", 0)),
                kd=float(c.get("kd", 0)),
                i_clamp=float(c.get("i_clamp", 0.5)),
            )
            print(f"  wrote {out} — reflash to bake defaults: rosie mcu flash")
            continue
        if cmd in ("kp", "ki", "kd", "i_clamp") and len(parts) >= 2:
            try:
                val = float(parts[1])
            except ValueError:
                print("  expected a number")
                continue
            bot.set_gains(**{cmd: val})
            time.sleep(0.15)
            continue
        print("  unknown command")
    return 0


def cmd_tune(args: Any) -> int:
    """Entry for ``rosie tune`` / ``rosie tune set`` / ``rosie tune save``."""
    from pathlib import Path

    from rosie.robot import Robot
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
            # Pull live gains from robot
            bot = Robot(
                robot=args.robot,
                fleet=args.fleet,
                connect=args.connect,
                name="tune",
                config_path=config,
            )
            msg = _latest_control(bot)
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
        print("Reflash to bake defaults: rosie mcu flash")
        return 0

    bot = Robot(
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
            print("error: pass at least one of --kp/--ki/--kd/--i-clamp", file=sys.stderr)
            return 2
        bot.set_gains(**kwargs)
        print(f"set_gains {kwargs}")
        time.sleep(0.3)
        msg = _latest_control(bot)
        if msg:
            print(
                f"robot: kp={msg.get('kp')} ki={msg.get('ki')} "
                f"kd={msg.get('kd')} i_clamp={msg.get('i_clamp')}"
            )
        return 0

    # interactive (default)
    return run_tune_interactive(bot, config_path=config)
