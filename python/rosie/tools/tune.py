"""Live velocity-PID tuning helpers (no argparse).

Call from scripts or ``rosie tune`` (CLI lives in ``rosie.cli.tune``).
"""

from __future__ import annotations

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


def latest_control(bot: Any, timeout_s: float = 2.0) -> dict | None:
    """Request gains and wait for a ``control`` telemetry sample."""
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
    """Interactive gain editor. Keys: kp/ki/kd/i_clamp, get, save, quit."""
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
