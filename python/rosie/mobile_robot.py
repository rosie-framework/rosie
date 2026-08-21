"""Host-side MobileBase client: goto, teleop, camera on a Rosie Session."""

from __future__ import annotations

import math
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
from rosie.session import Qos
from rosie.std_msgs import Cmd, Goto, Twist
from rosie.tools.teleop_twist import run_teleop


def _wrap_deg(delta: float) -> float:
    """Wrap a degree delta to (−180, 180]."""
    return (float(delta) + 180.0) % 360.0 - 180.0


def _msg_cmd(op: str, value: Any = None) -> bytes:
    if isinstance(value, bool):
        return encode_json({"op": op, "value": value})
    if value is None:
        return Cmd(op=op).to_bytes()
    return encode_json({"op": op, "value": value})


_CMD_QOS = Qos.COMMAND


class MobileRobot:
    """Host-side helper for a MobileBase / DiffDriveStack robot.

    Sibling capability clients (e.g. an arm helper) would wrap ``Session`` the
    same way — there is no shared robot superclass.

    Navigation (topics only — see docs/robots/mobile-base.md):
      ``goto`` — publish a planar goal with ``goal_id`` (fire-and-forget)
      ``pose`` — progress (``navigating``, ``dist``, ``goal_id``)
      ``nav_result`` — terminal outcome (``succeeded`` / ``canceled``;
      ``aborted`` is reserved — hosts must tolerate it, robots do not emit it)
      ``drive_to`` — blocking helper: goto + wait for matching ``nav_result``
      ``drive_route`` — convenience: sequential ``drive_to`` (not a planner)
      ``drive`` — relative distance on wheel odometry (host ``cmd_vel`` loop)
      ``turn`` — relative heading on pose (host ``cmd_vel`` loop)

    Also: teleop, camera, pose, gains. Interactive UX: ``rosie drive``.
    """

    def __init__(
        self,
        robot: str | None = None,
        *,
        fleet: str | None = None,
        connect: str | None = None,
        name: str = "mobile",
        config_path: str | Path | None = None,
        secure: bool = False,
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
            # Prefer explicit password from robot.yaml when present.
            user = cfg.zenoh_user
            password = cfg.fleet_secret
        else:
            self._v_fwd = 0.25
            self._v_turn = 1.2
            user = None
            password = None

        robot = robot or os.environ.get("ROSIE_ROBOT", "robot")
        self.session = Session(
            robot=robot,
            fleet=fleet,
            connect=connect,
            name=name,
            user=user,
            password=password,
            secure=secure and not password,
        )
        self.robot_id = robot
        self._pose: dict = {}
        self._nav_result: dict | None = None
        self._next_goal_id = 1
        self._lock = threading.Lock()
        self.session.subscribe_json(topics.POSE, self._on_pose)
        self.session.subscribe_json(topics.NAV_RESULT, self._on_nav_result)

    def _on_pose(self, msg: dict) -> None:
        with self._lock:
            self._pose = msg

    def _on_nav_result(self, msg: dict) -> None:
        with self._lock:
            self._nav_result = msg

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
        self.session.publish(topics.CMD, _msg_cmd("stop"), qos=_CMD_QOS)

    def _publish_twist(self, v: float, w: float) -> None:
        self.session.publish_msg(topics.CMD_VEL, Twist(v=float(v), w=float(w)))

    def _halt(self) -> None:
        self._publish_twist(0.0, 0.0)
        self.stop()

    @staticmethod
    def _heading_deg(pose: dict) -> float:
        if pose.get("heading_deg") is not None:
            return float(pose["heading_deg"])
        return math.degrees(float(pose.get("theta", 0.0)))

    def _require_pose(self, timeout_s: float = 3.0) -> dict:
        p = self.wait_for_pose(timeout_s)
        if not p:
            raise TimeoutError(f"no pose received within {timeout_s}s")
        return p

    def drive(
        self,
        meters: float,
        speed: float = 0.25,
        *,
        hz: float = 10.0,
        timeout_s: float | None = None,
    ) -> dict:
        """Drive a signed distance on wheel odometry. Negative ``meters`` reverses.

        Streams ``cmd_vel`` (deadman) and stops when planar displacement from the
        start pose reaches ``abs(meters)``. Ctrl-C sends ``stop`` and re-raises.
        Returns the pose at halt.
        """
        meters = float(meters)
        speed = float(speed)
        if speed <= 0.0:
            raise ValueError("speed must be > 0")
        if hz <= 0.0:
            raise ValueError("hz must be > 0")
        if abs(meters) < 1e-9:
            self._halt()
            return self.pose()

        start = self._require_pose()
        sx = float(start.get("x", 0.0))
        sy = float(start.get("y", 0.0))
        target = abs(meters)
        v = math.copysign(speed, meters)
        if timeout_s is None:
            timeout_s = max(5.0, target / speed * 2.0 + 2.0)
        period = 1.0 / hz
        deadline = time.monotonic() + float(timeout_s)
        print(
            f"  drive {meters:+.3f} m at {speed:.2f} m/s ...  (Ctrl-C to send STOP)"
        )
        try:
            while True:
                if time.monotonic() >= deadline:
                    self._halt()
                    print()
                    raise TimeoutError(
                        f"drive did not reach {target:.3f} m within {timeout_s}s"
                    )
                p = self.pose()
                traveled = math.hypot(
                    float(p.get("x", sx)) - sx, float(p.get("y", sy)) - sy
                )
                remaining = target - traveled
                if remaining <= 0.0:
                    break
                self._publish_twist(v, 0.0)
                sys.stdout.write(
                    f"\r  pose:  x={p.get('x', 0):7.3f} m   y={p.get('y', 0):7.3f} m   "
                    f"traveled={traveled:6.3f} m   remaining={remaining:6.3f} m   "
                )
                sys.stdout.flush()
                time.sleep(period)
        except KeyboardInterrupt:
            self._halt()
            print("\n  STOP sent.")
            raise
        self._halt()
        print()
        return self.pose()

    def turn(
        self,
        degrees: float,
        rate_dps: float = 60,
        *,
        hz: float = 10.0,
        timeout_s: float | None = None,
    ) -> dict:
        """Turn in place by a signed heading angle (degrees, +left / CCW).

        Streams ``cmd_vel`` yaw (deadman) and stops when accumulated heading
        change on pose reaches ``abs(degrees)``. Ctrl-C sends ``stop`` and
        re-raises. Returns the pose at halt.
        """
        degrees = float(degrees)
        rate_dps = float(rate_dps)
        if rate_dps <= 0.0:
            raise ValueError("rate_dps must be > 0")
        if hz <= 0.0:
            raise ValueError("hz must be > 0")
        if abs(degrees) < 1e-9:
            self._halt()
            return self.pose()

        start = self._require_pose()
        last_h = self._heading_deg(start)
        target = abs(degrees)
        w = math.copysign(math.radians(rate_dps), degrees)
        if timeout_s is None:
            timeout_s = max(5.0, target / rate_dps * 2.0 + 2.0)
        period = 1.0 / hz
        deadline = time.monotonic() + float(timeout_s)
        traveled = 0.0
        print(
            f"  turn {degrees:+.1f} deg at {rate_dps:.0f} deg/s ...  (Ctrl-C to send STOP)"
        )
        try:
            while True:
                if time.monotonic() >= deadline:
                    self._halt()
                    print()
                    raise TimeoutError(
                        f"turn did not reach {target:.1f} deg within {timeout_s}s"
                    )
                p = self.pose()
                h = self._heading_deg(p)
                traveled += abs(_wrap_deg(h - last_h))
                last_h = h
                remaining = target - traveled
                if remaining <= 0.0:
                    break
                self._publish_twist(0.0, w)
                sys.stdout.write(
                    f"\r  pose:  heading={h:7.1f} deg   "
                    f"turned={traveled:6.1f} deg   remaining={remaining:6.1f} deg   "
                )
                sys.stdout.flush()
                time.sleep(period)
        except KeyboardInterrupt:
            self._halt()
            print("\n  STOP sent.")
            raise
        self._halt()
        print()
        return self.pose()

    def zero(self) -> None:
        self.session.publish(topics.CMD, _msg_cmd("zero"), qos=_CMD_QOS)

    def set_heading_source(self, imu: bool | None = None) -> None:
        if imu is None:
            self.session.publish(
                topics.CMD, _msg_cmd("heading_source"), qos=_CMD_QOS
            )
        else:
            self.session.publish(
                topics.CMD,
                _msg_cmd("heading_source", bool(imu)),
                qos=_CMD_QOS,
            )

    def set_camera_enable(self, enable: bool = True) -> None:
        self.session.publish(
            topics.CMD, _msg_cmd("camera_enable", bool(enable)), qos=_CMD_QOS
        )

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
        self.session.publish(
            topics.CMD, _msg_cmd("set_gains", value), qos=_CMD_QOS
        )

    def get_gains(self) -> None:
        """Request gain / control telemetry publish (see topics.CONTROL)."""
        self.session.publish(topics.CMD, _msg_cmd("get_gains"), qos=_CMD_QOS)

    def goto(self, x: float, y: float, *, goal_id: int | None = None) -> int:
        """Publish a planar goal (fire-and-forget). Returns ``goal_id``.

        The navigation primitive. Completion is published on ``nav_result``.
        """
        if goal_id is None:
            goal_id = self._next_goal_id
            self._next_goal_id += 1
        else:
            self._next_goal_id = max(self._next_goal_id, int(goal_id) + 1)
        with self._lock:
            self._nav_result = None
        self.session.publish(
            topics.GOTO,
            Goto(x=float(x), y=float(y), goal_id=int(goal_id)).to_bytes(),
            qos=_CMD_QOS,
        )
        return int(goal_id)

    def drive_to(
        self,
        x: float,
        y: float,
        poll_s: float = 0.1,
        *,
        timeout_s: float = 120.0,
    ) -> dict:
        """Blocking helper: ``goto``, then wait for matching ``nav_result``.

        Prints pose progress. Ctrl-C sends ``stop`` and re-raises.
        Raises ``TimeoutError`` if no matching ``nav_result`` within
        ``timeout_s`` (default 120 s).
        Returns the ``nav_result`` dict (``goal_id``, ``status``, …).
        """
        goal_id = self.goto(x, y)
        print(
            f"  driving to ({x}, {y}) m goal_id={goal_id} ...  (Ctrl-C to send STOP)"
        )
        deadline = time.monotonic() + float(timeout_s)
        try:
            while True:
                with self._lock:
                    result = dict(self._nav_result) if self._nav_result else None
                if result is not None and int(result.get("goal_id", -1)) == goal_id:
                    status = result.get("status", "?")
                    print()
                    print(
                        f"  >> nav_result goal_id={goal_id} status={status} "
                        f"at ({result.get('x', 0):.3f}, {result.get('y', 0):.3f}) m"
                    )
                    if status != "succeeded":
                        raise RuntimeError(
                            f"navigation {status} for goal_id={goal_id}"
                        )
                    return result
                if time.monotonic() >= deadline:
                    self.stop()
                    print()
                    raise TimeoutError(
                        f"no nav_result for goal_id={goal_id} within {timeout_s}s"
                    )
                p = self.pose()
                if p:
                    sys.stdout.write(
                        f"\r  pose:  x={p.get('x', 0):7.3f} m   y={p.get('y', 0):7.3f} m   "
                        f"heading={p.get('heading_deg', 0):7.1f} deg   "
                        f"remaining={p.get('dist', 0):6.3f} m   mode={p.get('mode', '?')}   "
                    )
                    sys.stdout.flush()
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.stop()
            print("\n  STOP sent.")
            raise

    def drive_route(self, waypoints: list[tuple[float, float]]) -> None:
        """Convenience: call ``drive_to`` for each waypoint. Not a path planner."""
        total = len(waypoints)
        for i, (x, y) in enumerate(waypoints, start=1):
            print(f"  waypoint {i}/{total}")
            try:
                self.drive_to(x, y)
            except KeyboardInterrupt:
                return
            except RuntimeError as e:
                print(f"  route stopped: {e}")
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

    def __enter__(self) -> MobileRobot:
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
