"""High-level Robot client: mission, teleop, camera on a Rosie Session."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rosie import Session, topics
from rosie.messages import encode_json
from rosie.std_msgs import Cmd, Goto
from rosie.tools.teleop_twist import run_teleop


def _msg_cmd(op: str, value: Any = None) -> bytes:
    if isinstance(value, bool):
        return encode_json({"op": op, "value": value})
    if value is None:
        return Cmd(op=op).to_bytes()
    return encode_json({"op": op, "value": value})


class Robot:
    """Host-side helper for a MobileBase robot (goto, teleop, camera, pose)."""

    def __init__(
        self,
        robot: str | None = None,
        *,
        fleet: str | None = None,
        connect: str | None = None,
        name: str = "robot",
        config_path: str | Path | None = None,
    ) -> None:
        if config_path:
            from rosie.robot_config import load_robot_config

            cfg = load_robot_config(config_path)
            robot = robot or cfg.robot
            fleet = fleet if fleet is not None else cfg.fleet
            connect = connect or cfg.connect
            teleop = (cfg.raw.get("control") or {}).get("teleop") or {}
            # Historical host teleop uses m/s; YAML kv/kw are firmware PWM gains.
            self._v_fwd = float(teleop.get("v_fwd", 0.25))
            self._v_turn = float(teleop.get("v_turn", 1.2))
        else:
            self._v_fwd = 0.25
            self._v_turn = 1.2

        robot = robot or os.environ.get("ROSIE_ROBOT", "robot")
        self.session = Session(robot=robot, fleet=fleet, connect=connect, name=name)
        self.robot_id = robot
        self._pose: dict = {}
        self._lock = threading.Lock()
        self.session.subscribe_json(topics.POSE, self._on_pose)

    def _on_pose(self, msg: dict) -> None:
        with self._lock:
            self._pose = msg

    def pose(self) -> dict:
        with self._lock:
            return dict(self._pose)

    def wait_for_pose(self, timeout_s: float = 3.0) -> dict | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            p = self.pose()
            if p:
                return p
            time.sleep(0.1)
        return None

    def stop(self) -> None:
        self.session.publish(topics.CMD, _msg_cmd("stop"))

    def zero(self) -> None:
        self.session.publish(topics.CMD, _msg_cmd("zero"))

    def set_heading_source(self, imu: bool | None = None) -> None:
        if imu is None:
            self.session.publish(topics.CMD, _msg_cmd("heading_source"))
        else:
            self.session.publish(topics.CMD, _msg_cmd("heading_source", bool(imu)))

    def set_camera_enable(self, enable: bool = True) -> None:
        self.session.publish(topics.CMD, _msg_cmd("camera_enable", bool(enable)))

    def set_gains(
        self,
        *,
        kp: float | None = None,
        ki: float | None = None,
        kd: float | None = None,
        i_clamp: float | None = None,
    ) -> None:
        """Live-update onboard velocity PID gains (partial OK)."""
        value: dict[str, float] = {}
        if kp is not None:
            value["kp"] = float(kp)
        if ki is not None:
            value["ki"] = float(ki)
        if kd is not None:
            value["kd"] = float(kd)
        if i_clamp is not None:
            value["i_clamp"] = float(i_clamp)
        if not value:
            raise ValueError("set_gains requires at least one of kp, ki, kd, i_clamp")
        self.session.publish(topics.CMD, _msg_cmd("set_gains", value))

    def get_gains(self) -> None:
        """Request gain / control telemetry publish (see topics.CONTROL)."""
        self.session.publish(topics.CMD, _msg_cmd("get_gains"))

    def goto(self, x: float, y: float) -> None:
        self.session.publish(topics.GOTO, Goto(x=float(x), y=float(y)).to_bytes())

    def drive_to(self, x: float, y: float, poll_s: float = 0.1) -> None:
        self.goto(x, y)
        print(f"  driving to ({x}, {y}) m ...  (Ctrl-C to send STOP)")
        try:
            saw_nav = False
            idle_checks = 0
            while True:
                p = self.pose()
                if p:
                    sys.stdout.write(
                        f"\r  pose:  x={p.get('x', 0):7.3f} m   y={p.get('y', 0):7.3f} m   "
                        f"heading={p.get('heading_deg', 0):7.1f} deg   "
                        f"remaining={p.get('dist', 0):6.3f} m   mode={p.get('mode', '?')}   "
                    )
                    sys.stdout.flush()
                    nav = bool(p.get("navigating", False))
                    if nav:
                        saw_nav = True
                        idle_checks = 0
                    elif saw_nav:
                        print()
                        print(f"  >> Arrived at ({p.get('x', 0):.3f}, {p.get('y', 0):.3f}) m")
                        return
                    else:
                        idle_checks += 1
                        if idle_checks > 20 and p.get("dist", 999) < 0.05:
                            print()
                            print(f"  >> Near goal at ({p.get('x', 0):.3f}, {p.get('y', 0):.3f}) m")
                            return
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.stop()
            print("\n  STOP sent.")
            raise

    def drive_route(self, waypoints: list[tuple[float, float]]) -> None:
        total = len(waypoints)
        for i, (x, y) in enumerate(waypoints, start=1):
            print(f"  waypoint {i}/{total}")
            try:
                self.drive_to(x, y)
            except KeyboardInterrupt:
                return
        print(f"  route complete ({total} waypoint{'s' if total != 1 else ''}).")

    def teleop(self, v_fwd: float | None = None, v_turn: float | None = None, hz: float = 10.0) -> None:
        run_teleop(
            self.session,
            v_fwd=v_fwd if v_fwd is not None else self._v_fwd,
            v_turn=v_turn if v_turn is not None else self._v_turn,
            pub_hz=hz,
            on_stop=self.stop,
        )

    def snap(
        self,
        timeout_s: float = 5.0,
        *,
        capture_dir: Path | None = None,
        open_viewer: bool = True,
    ) -> Path:
        buf = _CameraBuffer()
        self.set_camera_enable(True)
        self.session.subscribe_bytes(topics.CAMERA_COMPRESSED, buf.update)
        deadline = time.time() + timeout_s
        jpeg = None
        while time.time() < deadline:
            jpeg = buf.latest()
            if jpeg:
                break
            time.sleep(0.05)
        if not jpeg:
            raise TimeoutError(
                f"no JPEG on {topics.CAMERA_COMPRESSED} within {timeout_s}s"
            )
        out_dir = capture_dir or Path.cwd() / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"capture_{stamp}.jpg"
        out.write_bytes(jpeg)
        print(f"  saved {out} ({len(jpeg)} bytes)")
        if open_viewer:
            _open_image(out)
        return out

    def camera_live(self, duration_s: float | None = None) -> None:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            use_cv = True
        except ImportError:
            use_cv = False
            print("  (opencv not installed — printing frame sizes only)")

        buf = _CameraBuffer()
        self.set_camera_enable(True)
        self.session.subscribe_bytes(topics.CAMERA_COMPRESSED, buf.update)
        print("Live camera (Ctrl-C to stop)...")
        start = time.time()
        last_shown = 0.0
        try:
            while duration_s is None or (time.time() - start) < duration_s:
                jpeg = buf.latest(max_age_s=2.0)
                if jpeg and time.time() - last_shown > 0.05:
                    last_shown = time.time()
                    if use_cv:
                        arr = np.frombuffer(jpeg, dtype=np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if img is not None:
                            cv2.imshow(f"{self.robot_id}/camera", img)
                            if cv2.waitKey(1) & 0xFF == ord("q"):
                                break
                    else:
                        print(f"\r  frame {len(jpeg)} bytes   ", end="", flush=True)
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            if use_cv:
                cv2.destroyAllWindows()
            print("\nLive camera stopped.")

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Robot:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _CameraBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._stamp = 0.0

    def update(self, data: bytes) -> None:
        with self._lock:
            self._jpeg = data
            self._stamp = time.time()

    def latest(self, max_age_s: float = 5.0) -> bytes | None:
        with self._lock:
            if self._jpeg is None:
                return None
            if time.time() - self._stamp > max_age_s:
                return None
            return self._jpeg


def _open_image(path: Path) -> None:
    path = path.resolve()
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as e:
        print(f"  warning: could not open viewer ({e}); file is at {path}")
