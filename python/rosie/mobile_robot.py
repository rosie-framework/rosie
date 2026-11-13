"""Host-side client for a ROS 2 robot described by a profile."""

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

from rosie.profiles import RobotProfile, TopicBinding, load_profile
from rosie.ros.action import STATUS_SUCCEEDED, NavigateToPoseClient, nav_status_name
from rosie.ros.keys import qualify_topic
from rosie.ros.pose import pose_dict, twist_dict
from rosie.session import Qos, Session
from rosie.tools.teleop_twist import run_teleop


def _wrap_deg(delta: float) -> float:
    """Wrap a degree delta to (−180, 180]."""
    return (float(delta) + 180.0) % 360.0 - 180.0


def _relative(profile: RobotProfile, topic: str) -> str:
    return qualify_topic(profile.ros_namespace, topic).lstrip("/")


class MobileRobot:
    """Drive one fleet robot through its profile.

    Pose and velocity are ROS messages on the Zenoh keys the bridge (or
    rmw_zenoh) uses. ``goto`` / ``drive_to`` call Nav2's NavigateToPose
    action. ``stop`` sends a zero twist and cancels the active goal.
    """

    def __init__(
        self,
        robot: str | None = None,
        *,
        fleet: str | None = None,
        connect: str | None = None,
        name: str = "mobile",
        profile: str | RobotProfile = "default_ros2",
        profile_overrides: dict[str, Any] | None = None,
        secure: bool = False,
        v_fwd: float = 0.25,
        v_turn: float = 1.2,
    ) -> None:
        if isinstance(profile, RobotProfile):
            self.profile = profile
        else:
            self.profile = load_profile(str(profile), profile_overrides)
        robot = robot or os.environ.get("ROSIE_ROBOT", "robot")
        self.session = Session(
            robot=robot,
            fleet=fleet,
            connect=connect,
            name=name,
            secure=secure,
        )
        self.robot_id = self.session.robot
        self._v_fwd = float(v_fwd)
        self._v_turn = float(v_turn)
        self._pose: dict = {}
        self._lock = threading.Lock()
        self._goal_id: bytes | None = None
        self._nav: NavigateToPoseClient | None = None
        if self.profile.nav_action and self.profile.transport == "bridge":
            self._nav = NavigateToPoseClient(
                self.session,
                fleet=self.session.fleet,
                robot=self.session.robot,
                action=self.profile.nav_action,
                frame_id=self.profile.frame_id,
                distro=self.profile.distro,
                transport=self.profile.transport,
            )
        pose_key = _relative(self.profile, self.profile.pose.topic)
        self.session.subscribe_ros(
            pose_key,
            self.profile.pose.type,
            self._on_pose,
            distro=self.profile.distro,
        )

    def _command_binding(self) -> TopicBinding:
        if not self.profile.cmd_vel_gate:
            return self.profile.cmd_vel
        topic = self.profile.cmd_vel.topic.rstrip("/") + "_teleop"
        return TopicBinding(topic, self.profile.cmd_vel.type, self.profile.cmd_vel.type_hash)

    def _on_pose(self, msg: dict) -> None:
        try:
            parsed = pose_dict(self.profile.pose.type, msg)
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self._pose = parsed

    def pose(self) -> dict:
        with self._lock:
            return dict(self._pose)

    def wait_for_pose(self, timeout_s: float = 3.0) -> dict | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            current = self.pose()
            if current:
                return current
            time.sleep(0.1)
        return None

    def _publish_twist(self, v: float, w: float) -> None:
        binding = self._command_binding()
        self.session.publish_ros(
            _relative(self.profile, binding.topic),
            binding.type,
            twist_dict(binding.type, v, w),
            distro=self.profile.distro,
            qos=Qos.STREAM,
            envelope=True,
            priority="interactive",
            ttl_s=1.0,
        )

    def stop(self) -> None:
        """Zero velocity and cancel an active Nav2 goal."""
        self._publish_twist(0.0, 0.0)
        goal = self._goal_id
        if goal is not None and self._nav is not None:
            try:
                self._nav.cancel(goal)
            except Exception:
                pass
            self._goal_id = None

    @staticmethod
    def _heading_deg(pose: dict) -> float:
        if pose.get("heading_deg") is not None:
            return float(pose["heading_deg"])
        return math.degrees(float(pose.get("theta", 0.0)))

    def _require_pose(self, timeout_s: float = 3.0) -> dict:
        current = self.wait_for_pose(timeout_s)
        if not current:
            raise TimeoutError(f"no pose received within {timeout_s}s")
        return current

    def drive(
        self,
        meters: float,
        speed: float = 0.25,
        *,
        hz: float = 10.0,
        timeout_s: float | None = None,
    ) -> dict:
        """Drive a signed distance using pose feedback. Negative reverses."""
        meters = float(meters)
        speed = float(speed)
        if speed <= 0.0:
            raise ValueError("speed must be > 0")
        if hz <= 0.0:
            raise ValueError("hz must be > 0")
        if abs(meters) < 1e-9:
            self.stop()
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
        print(f"  drive {meters:+.3f} m at {speed:.2f} m/s ...  (Ctrl-C to stop)")
        try:
            while True:
                if time.monotonic() >= deadline:
                    self.stop()
                    print()
                    raise TimeoutError(
                        f"drive did not reach {target:.3f} m within {timeout_s}s"
                    )
                current = self.pose()
                traveled = math.hypot(
                    float(current.get("x", sx)) - sx,
                    float(current.get("y", sy)) - sy,
                )
                remaining = target - traveled
                if remaining <= 0.0:
                    break
                self._publish_twist(v, 0.0)
                sys.stdout.write(
                    f"\r  pose:  x={current.get('x', 0):7.3f} m   "
                    f"y={current.get('y', 0):7.3f} m   "
                    f"traveled={traveled:6.3f} m   remaining={remaining:6.3f} m   "
                )
                sys.stdout.flush()
                time.sleep(period)
        except KeyboardInterrupt:
            self.stop()
            print("\n  STOP sent.")
            raise
        self.stop()
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
        """Turn in place by a signed heading angle (degrees, +left / CCW)."""
        degrees = float(degrees)
        rate_dps = float(rate_dps)
        if rate_dps <= 0.0:
            raise ValueError("rate_dps must be > 0")
        if hz <= 0.0:
            raise ValueError("hz must be > 0")
        if abs(degrees) < 1e-9:
            self.stop()
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
            f"  turn {degrees:+.1f} deg at {rate_dps:.0f} deg/s ...  (Ctrl-C to stop)"
        )
        try:
            while True:
                if time.monotonic() >= deadline:
                    self.stop()
                    print()
                    raise TimeoutError(
                        f"turn did not reach {target:.1f} deg within {timeout_s}s"
                    )
                current = self.pose()
                heading = self._heading_deg(current)
                traveled += abs(_wrap_deg(heading - last_h))
                last_h = heading
                remaining = target - traveled
                if remaining <= 0.0:
                    break
                self._publish_twist(0.0, w)
                sys.stdout.write(
                    f"\r  pose:  heading={heading:7.1f} deg   "
                    f"turned={traveled:6.1f} deg   remaining={remaining:6.1f} deg   "
                )
                sys.stdout.flush()
                time.sleep(period)
        except KeyboardInterrupt:
            self.stop()
            print("\n  STOP sent.")
            raise
        self.stop()
        print()
        return self.pose()

    def goto(self, x: float, y: float, *, yaw: float = 0.0) -> bytes:
        """Send a NavigateToPose goal. Returns the 16-byte goal id."""
        if self._nav is None:
            raise RuntimeError(
                f"profile {self.profile.name!r} has no NavigateToPose action"
            )
        goal_id = self._nav.send_goal(x, y, yaw=yaw)
        self._goal_id = goal_id
        return goal_id

    def drive_to(
        self,
        x: float,
        y: float,
        *,
        timeout_s: float = 120.0,
        poll_s: float = 0.2,
    ) -> dict:
        """Blocking helper: send a goal, then wait for its result."""
        if self._nav is None:
            raise RuntimeError(
                f"profile {self.profile.name!r} has no NavigateToPose action"
            )
        goal_id = self.goto(x, y)
        print(f"  driving to ({x}, {y}) m ...  (Ctrl-C to stop)")
        holder: dict[str, Any] = {}
        error: list[BaseException] = []

        def _wait() -> None:
            try:
                holder["result"] = self._nav.wait_result(goal_id, timeout_s=timeout_s)
            except BaseException as exc:  # noqa: BLE001 - surfaced on the caller thread
                error.append(exc)

        thread = threading.Thread(target=_wait, name="rosie-nav-result", daemon=True)
        thread.start()
        deadline = time.monotonic() + float(timeout_s)
        try:
            while thread.is_alive():
                if time.monotonic() >= deadline:
                    self.stop()
                    raise TimeoutError(f"no nav result within {timeout_s}s")
                current = self.pose()
                if current:
                    sys.stdout.write(
                        f"\r  pose:  x={current.get('x', 0):7.3f} m   "
                        f"y={current.get('y', 0):7.3f} m   "
                        f"heading={current.get('heading_deg', 0):7.1f} deg   "
                    )
                    sys.stdout.flush()
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.stop()
            print("\n  STOP sent.")
            raise
        thread.join(timeout=1.0)
        if error:
            raise error[0]
        result = holder.get("result") or {}
        status = nav_status_name(int(result.get("status") or 0))
        print()
        print(f"  >> nav result status={status}")
        if status != "succeeded" and int(result.get("status") or 0) != STATUS_SUCCEEDED:
            raise RuntimeError(f"navigation {status}")
        return result

    def drive_route(self, waypoints: list[tuple[float, float]]) -> None:
        """Call ``drive_to`` for each waypoint. Not a path planner."""
        total = len(waypoints)
        for i, (x, y) in enumerate(waypoints, start=1):
            print(f"  waypoint {i}/{total}")
            try:
                self.drive_to(x, y)
            except KeyboardInterrupt:
                return
            except RuntimeError as exc:
                print(f"  route stopped: {exc}")
                return
        print(f"  route complete ({total} waypoint{'s' if total != 1 else ''}).")

    def teleop(
        self,
        v_fwd: float | None = None,
        v_turn: float | None = None,
        hz: float = 10.0,
    ) -> None:
        run_teleop(
            self.session,
            v_fwd=v_fwd if v_fwd is not None else self._v_fwd,
            v_turn=v_turn if v_turn is not None else self._v_turn,
            pub_hz=hz,
            publish=self._publish_twist,
            on_stop=self.stop,
        )

    def snap(
        self,
        timeout_s: float = 5.0,
        *,
        capture_dir: Path | None = None,
        open_viewer: bool = True,
    ) -> Path:
        if self.profile.camera is None:
            raise RuntimeError(f"profile {self.profile.name!r} has no camera topic")
        holder: dict[str, bytes] = {}

        def _on(msg: dict) -> None:
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)) and data:
                holder["jpeg"] = bytes(data)

        self.session.subscribe_ros(
            _relative(self.profile, self.profile.camera.topic),
            self.profile.camera.type,
            _on,
            distro=self.profile.distro,
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline and "jpeg" not in holder:
            time.sleep(0.05)
        jpeg = holder.get("jpeg")
        if not jpeg:
            raise TimeoutError(f"no camera frame within {timeout_s}s")
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
        if self.profile.camera is None:
            raise RuntimeError(f"profile {self.profile.name!r} has no camera topic")
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            use_cv = True
        except ImportError:
            use_cv = False
            print("  (opencv not installed — printing frame sizes only)")

        latest: dict[str, bytes] = {}

        def _on(msg: dict) -> None:
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)) and data:
                latest["jpeg"] = bytes(data)

        self.session.subscribe_ros(
            _relative(self.profile, self.profile.camera.topic),
            self.profile.camera.type,
            _on,
            distro=self.profile.distro,
        )
        print("Live camera (Ctrl-C to stop)...")
        start = time.time()
        last_shown = 0.0
        try:
            while duration_s is None or (time.time() - start) < duration_s:
                jpeg = latest.get("jpeg")
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
    except OSError as exc:
        print(f"  warning: could not open viewer ({exc}); file is at {path}")
