"""Run / init / install / doctor for ``rosie agent``."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

from rosie import topics
from rosie.connect import resolve_connect
from rosie.messages import encode_json
from rosie.agent.config import (
    AgentConfig,
    default_config_path,
    load_agent_config,
    write_agent_config,
)


def run_agent(cfg: AgentConfig) -> int:
    """Foreground ROS 2 ↔ Rosie bridge (blocks until interrupt)."""
    from rosie.agent.backends.ros2 import Ros2Bridge
    from rosie.session import Session

    session: Session | None = None
    bridge = None
    stop = threading.Event()

    def _on_signal(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        if cfg.path is not None:
            from rosie.auth import maybe_sync_secret_for_agent_config

            if maybe_sync_secret_for_agent_config(cfg.path, cfg.raw):
                print(f"Synced bus secret → {cfg.path.name}", file=sys.stderr)
                cfg = load_agent_config(cfg.path)

        session = Session(
            robot=cfg.robot,
            fleet=cfg.fleet,
            connect=cfg.connect,
            name="agent",
            user=cfg.user or (cfg.fleet if cfg.fleet_secret else None),
            password=cfg.fleet_secret,
        )
        bridge = Ros2Bridge(session, cfg)
        bridge.start()
        fleet_s = f" fleet={cfg.fleet}" if cfg.fleet else ""
        print(
            f"Rosie agent online robot={cfg.robot}{fleet_s} "
            f"connect={session.connect}",
            file=sys.stderr,
        )

        def beat() -> None:
            while not stop.is_set() and session is not None:
                try:
                    payload = {
                        "robot_id": session.robot,
                        "status": "ready",
                    }
                    if session.fleet:
                        payload["fleet_id"] = session.fleet
                    session.publish(topics.PRESENCE, encode_json(payload))
                except Exception as e:
                    print(f"presence publish failed: {e}", file=sys.stderr)
                stop.wait(1.0)

        threading.Thread(target=beat, name="rosie-agent-presence", daemon=True).start()

        while not stop.is_set():
            bridge.spin_once(timeout_sec=0.05)
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        stop.set()
        if bridge is not None:
            try:
                bridge.shutdown()
            except Exception:
                pass
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
            print("Rosie agent stopped.", file=sys.stderr)
    return 0


def init_agent(
    *,
    path: str | Path | None = None,
    robot: str | None = None,
    fleet: str | None = None,
    connect: str | None = None,
    profile: str | None = None,
    force: bool = False,
) -> Path:
    """Write ``agent.yaml`` and return its path."""
    out = Path(path).expanduser().resolve() if path else default_config_path()
    if out.is_file() and not force:
        raise FileExistsError(
            f"{out} already exists (pass --force to overwrite)"
        )
    robot_id = robot or os.environ.get("ROSIE_ROBOT") or "robot"
    fleet_id = fleet if fleet is not None else os.environ.get("ROSIE_FLEET")
    if not fleet_id:
        raise ValueError("--fleet or ROSIE_FLEET is required")
    connect_id = connect if connect is not None else os.environ.get("ROSIE_CONNECT")
    # Resolve topics from profile
    cfg = load_agent_config(
        None,
        robot=robot_id,
        fleet=fleet_id,
        connect=connect_id,
        profile=profile,
    )
    cfg.path = out
    write_agent_config(out, cfg)
    return out


def install_agent(
    *,
    config_path: str | Path | None = None,
    working_directory: str | Path | None = None,
) -> Path:
    """Write a systemd --user unit and print enable instructions."""
    cfg_path = (
        Path(config_path).expanduser().resolve()
        if config_path
        else default_config_path()
    )
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"agent config not found: {cfg_path}\n"
            "  Run `rosie agent init` first."
        )
    cfg = load_agent_config(cfg_path)
    workdir = (
        Path(working_directory).expanduser().resolve()
        if working_directory
        else cfg_path.parent
    )
    # Prefer the active interpreter's rosie entrypoint
    exe = sys.executable
    # Use `python -m rosie.cli` if console script path is unknown; prefer `rosie`
    rosie_bin = _find_rosie_bin()
    if rosie_bin:
        exec_start = f"{rosie_bin} agent run --config {cfg_path}"
    else:
        exec_start = f"{exe} -m rosie.cli agent run --config {cfg_path}"

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "rosie-agent.service"

    env_lines = []
    if cfg.robot:
        env_lines.append(f"Environment=ROSIE_ROBOT={cfg.robot}")
    if cfg.fleet:
        env_lines.append(f"Environment=ROSIE_FLEET={cfg.fleet}")

    unit = f"""[Unit]
Description=Rosie agent (ROS 2 ↔ Rosie bridge)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={exec_start}
Restart=on-failure
RestartSec=2
{chr(10).join(env_lines)}

[Install]
WantedBy=default.target
"""
    unit_path.write_text(unit, encoding="utf-8")
    return unit_path


def _find_rosie_bin() -> str | None:
    import shutil

    return shutil.which("rosie")


def doctor(cfg: AgentConfig) -> int:
    """Check config, rclpy, and router connectivity. Return exit code."""
    ok = True
    print(f"robot:    {cfg.robot}")
    print(f"fleet:    {cfg.fleet or '—'}")
    from rosie.connect import is_auto_connect

    connect = resolve_connect(cfg.connect)
    if is_auto_connect(connect):
        print(f"connect:  {connect} (will scout + verify fleet)")
    else:
        print(f"connect:  {connect}")
    print(f"cmd_vel:  {cfg.cmd_vel}")
    print(f"odom:     {cfg.odom}")
    pose_src = cfg.pose or cfg.odom
    pose_note = " (ROS pose topic)" if cfg.pose else " (from odom)"
    print(f"pose:     {pose_src}{pose_note}")
    print(f"nav2:     {cfg.navigate_to_pose}")
    print(f"frame:    {cfg.frame_id}")
    print(f"profile:  {cfg.profile or '—'}")
    if cfg.path:
        print(f"config:   {cfg.path}")
    if (cfg.frame_id or "map") == "map" and not cfg.pose:
        print(
            "warning:  frame_id is map but pose comes from odom; "
            "set ros2.pose (e.g. /amcl_pose) so goto coordinates match pose",
            file=sys.stderr,
        )

    try:
        from rosie.agent.backends.ros2 import require_rclpy

        require_rclpy()
        print("rclpy:    ok")
    except ImportError as e:
        print(f"rclpy:    FAIL\n{e}")
        ok = False

    try:
        from nav2_msgs.action import NavigateToPose  # noqa: F401

        print("nav2_msgs: ok")
    except ImportError:
        print("nav2_msgs: missing (goto will abort until Nav2 is installed)")

    try:
        from rosie.session import Session

        session = Session(
            robot=cfg.robot,
            fleet=cfg.fleet,
            connect=cfg.connect,
            name="agent-doctor",
        )
        session.close()
        print("zenoh:    ok (session opened)")
    except Exception as e:
        print(f"zenoh:    FAIL ({e})")
        ok = False

    if ok:
        print("doctor: all checks passed")
        return 0
    print("doctor: one or more checks failed", file=sys.stderr)
    return 1
