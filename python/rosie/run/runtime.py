"""MobileBase-equivalent control loop for Linux (``rosie run``)."""

from __future__ import annotations

import math
import signal
import sys
import threading
import time
from enum import Enum
from typing import Any

from rosie import topics
from rosie.run.drivers import (
    EncoderReader,
    ImuReader,
    MotorDriver,
    build_encoders,
    build_imu,
    build_motors,
    describe_hardware,
)
from rosie.run.goto import GotoGains, navigate_step
from rosie.run.kinematics import DiffDriveGeometry, DiffDriveKinematics, DiffDriveTeleop
from rosie.messages import encode_json
from rosie.robot_config import RobotConfig
from rosie.session import Session


class DriveMode(str, Enum):
    IDLE = "idle"
    MANUAL = "manual"
    AUTO = "auto"


class MobileBaseRuntime:
    """On-robot loop: cmd_vel / goto / cmd → motors; pose / presence / nav_result out."""

    def __init__(
        self,
        cfg: RobotConfig,
        *,
        motors: MotorDriver,
        encoders: EncoderReader | None = None,
        imu: ImuReader | None = None,
        robot: str | None = None,
        fleet: str | None = None,
        connect: str | None = None,
    ) -> None:
        self.cfg = cfg
        self.motors = motors
        self.encoders = encoders
        self.imu = imu
        self._raw = cfg.raw
        control = self._raw.get("control") or {}
        teleop = control.get("teleop") or {}
        base = self._raw.get("base") or {}
        pwm = (self._raw.get("motors") or {}).get("pwm") or {}
        max_pwm = float(pwm.get("max", 100))
        if max_pwm <= 1.0:
            max_pwm = 100.0

        self.kinematics = DiffDriveKinematics(
            DiffDriveGeometry(
                wheel_diameter=float(base.get("wheel_diameter", 0.068)),
                wheel_base=float(base.get("wheel_base", 0.13)),
                ticks_per_rev=float(base.get("ticks_per_rev", 1440)),
            ),
            DiffDriveTeleop(
                kv=float(teleop.get("kv", 180)),
                kw=float(teleop.get("kw", 40)),
                max_pwm=max_pwm,
            ),
        )
        goto = control.get("goto") or {}
        self.goto_gains = GotoGains(
            kp_linear=float(goto.get("kp_linear", 0.8)),
            kp_angular=float(goto.get("kp_angular", 1.5)),
            v_max=float(goto.get("v_max", 0.35)),
            w_max=float(goto.get("w_max", 1.5)),
            pos_tolerance=float(goto.get("pos_tolerance", 0.025)),
            approach_dist=float(goto.get("approach_dist", 0.20)),
            align_tol=float(goto.get("align_tol", 0.52)),
        )
        self.dt_ms = int(control.get("dt_ms", 20))
        self.teleop_timeout_ms = int(teleop.get("timeout_ms", 400))
        self.pose_hz = float(control.get("pose_hz", 20))
        self.presence_hz = float(control.get("presence_hz", 1))

        self._lock = threading.Lock()
        self._cmd_v = 0.0
        self._cmd_w = 0.0
        self._last_cmd_vel_t = 0.0
        self._cmd_vel_seen = False
        self._stop_req = False
        self._zero_req = False
        self._goto_req = False
        self._goto_x = 0.0
        self._goto_y = 0.0
        self._goto_goal_id = 0
        self._goto_has_id = False
        self._next_goal_id = 1
        self._active_goal_id = 0
        self._navigating = False
        self._target_x = 0.0
        self._target_y = 0.0
        self._mode = DriveMode.IDLE

        self.session = Session(
            robot=robot or cfg.robot,
            fleet=fleet if fleet is not None else cfg.fleet,
            connect=connect or cfg.connect,
            name="run",
            user=cfg.zenoh_user,
            password=cfg.fleet_secret,
        )
        self.session.subscribe_json(topics.CMD_VEL, self._on_cmd_vel)
        self.session.subscribe_json(topics.GOTO, self._on_goto)
        self.session.subscribe_json(topics.CMD, self._on_cmd)

    def _on_cmd_vel(self, msg: dict) -> None:
        with self._lock:
            self._cmd_v = float(msg.get("v", 0.0))
            self._cmd_w = float(msg.get("w", 0.0))
            self._last_cmd_vel_t = time.monotonic()
            self._cmd_vel_seen = True

    def _on_goto(self, msg: dict) -> None:
        if "x" not in msg or "y" not in msg:
            return
        with self._lock:
            self._goto_x = float(msg["x"])
            self._goto_y = float(msg["y"])
            if msg.get("goal_id") is not None:
                self._goto_has_id = True
                self._goto_goal_id = int(msg["goal_id"])
            else:
                self._goto_has_id = False
            self._goto_req = True

    def _on_cmd(self, msg: dict) -> None:
        op = str(msg.get("op", ""))
        with self._lock:
            if op == "stop":
                self._stop_req = True
            elif op == "zero":
                self._zero_req = True

    def _publish_pose(self) -> None:
        p = self.kinematics.pose()
        dx = self._target_x - p.x
        dy = self._target_y - p.y
        doc: dict[str, Any] = {
            "x": p.x,
            "y": p.y,
            "theta": p.theta,
            "heading_deg": p.theta * 180.0 / math.pi,
            "dist": math.hypot(dx, dy),
            "navigating": self._navigating,
            "mode": self._mode.value,
        }
        if self._navigating:
            doc["goal_id"] = self._active_goal_id
        self.session.publish(topics.POSE, encode_json(doc))

    def _publish_presence(self) -> None:
        doc: dict[str, Any] = {
            "robot_id": self.session.robot,
            "status": "ready",
        }
        if self.session.fleet:
            doc["fleet_id"] = self.session.fleet
        self.session.publish(topics.PRESENCE, encode_json(doc))

    def _publish_nav_result(self, status: str) -> None:
        p = self.kinematics.pose()
        self.session.publish(
            topics.NAV_RESULT,
            encode_json(
                {
                    "goal_id": self._active_goal_id,
                    "status": status,
                    "x": p.x,
                    "y": p.y,
                }
            ),
        )

    def _log(self, level: str, msg: str) -> None:
        print(f"LOG[{level}] {msg}", file=sys.stderr)
        try:
            self.session.publish(
                topics.LOG, encode_json({"level": level, "msg": msg})
            )
        except Exception:
            pass

    def _end_nav(self, status: str) -> None:
        if not self._navigating:
            return
        self._navigating = False
        self._publish_nav_result(status)
        self._mode = DriveMode.IDLE
        self.motors.stop()
        self.kinematics.set_commanded_twist(0.0, 0.0)

    def _drive(self, v: float, w: float) -> None:
        self.kinematics.set_commanded_twist(v, w)
        channels = self.kinematics.twist_to_channels(v, w)
        self.motors.set_channels(channels)

    def tick(self) -> None:
        dt = self.dt_ms / 1000.0
        ticks = None
        if self.encoders is not None:
            ticks = self.encoders.read_ticks()
        yaw_rate = None
        if self.imu is not None:
            yaw_rate = self.imu.read_yaw_rate()
        self.kinematics.update_odometry(ticks, dt, yaw_rate)

        with self._lock:
            stop_req = self._stop_req
            zero_req = self._zero_req
            goto_req = self._goto_req
            cmd_vel_seen = self._cmd_vel_seen
            cmd_v, cmd_w = self._cmd_v, self._cmd_w
            last_cmd_t = self._last_cmd_vel_t
            goto_x, goto_y = self._goto_x, self._goto_y
            goto_has_id = self._goto_has_id
            goto_goal_id = self._goto_goal_id
            self._stop_req = False
            self._zero_req = False
            self._goto_req = False
            self._cmd_vel_seen = False

        if stop_req:
            if self._navigating:
                self._end_nav("canceled")
                self._log("info", "Stopped.")
            else:
                self._mode = DriveMode.IDLE
                self.motors.stop()
                self.kinematics.set_commanded_twist(0.0, 0.0)
                self._log("info", "Stopped.")

        if zero_req:
            if self._navigating:
                self._end_nav("canceled")
            self.kinematics.zero_pose()
            self._mode = DriveMode.IDLE
            self.motors.stop()
            self._log("info", "Pose zeroed.")

        if goto_req:
            if self._navigating:
                self._end_nav("canceled")
            self._target_x = goto_x
            self._target_y = goto_y
            if goto_has_id:
                self._active_goal_id = goto_goal_id
                if self._active_goal_id >= self._next_goal_id:
                    self._next_goal_id = self._active_goal_id + 1
            else:
                self._active_goal_id = self._next_goal_id
                self._next_goal_id += 1
            self._navigating = True
            self._mode = DriveMode.AUTO
            self._log(
                "info",
                f"New target: ({goto_x:.3f}, {goto_y:.3f}) m "
                f"goal_id={self._active_goal_id}",
            )

        if cmd_vel_seen:
            if self._navigating:
                self._end_nav("canceled")
            self._mode = DriveMode.MANUAL

        if self._mode == DriveMode.AUTO:
            if self._navigating:
                twist = navigate_step(
                    self.kinematics.pose(),
                    self._target_x,
                    self._target_y,
                    self.goto_gains,
                )
                if twist is None:
                    p = self.kinematics.pose()
                    self._log(
                        "info",
                        f"Arrived at ({p.x:.3f}, {p.y:.3f}) m, "
                        f"heading {p.theta * 180.0 / math.pi:.1f} deg",
                    )
                    self._end_nav("succeeded")
                else:
                    self._drive(twist[0], twist[1])
            else:
                self._mode = DriveMode.IDLE
        elif self._mode == DriveMode.MANUAL:
            age_ms = (time.monotonic() - last_cmd_t) * 1000.0
            if age_ms > self.teleop_timeout_ms:
                self.motors.stop()
                self.kinematics.set_commanded_twist(0.0, 0.0)
                self._mode = DriveMode.IDLE
                self._log("warn", "Teleop deadman timeout.")
            else:
                self._drive(cmd_v, cmd_w)

    def run(self) -> int:
        stop = threading.Event()

        def _sig(_s: int, _f: object) -> None:
            stop.set()

        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)

        fleet_s = f" fleet={self.session.fleet}" if self.session.fleet else ""
        print(
            f"Rosie run online robot={self.session.robot}{fleet_s} "
            f"connect={self.session.connect}",
            file=sys.stderr,
        )
        last_tick = time.monotonic()
        last_pose = 0.0
        last_presence = 0.0
        pose_period = 1.0 / self.pose_hz if self.pose_hz > 0.1 else 0.05
        presence_period = (
            1.0 / self.presence_hz if self.presence_hz > 0.1 else 1.0
        )
        dt = self.dt_ms / 1000.0

        try:
            while not stop.is_set():
                now = time.monotonic()
                if now - last_tick >= dt:
                    last_tick = now
                    self.tick()
                if now - last_pose >= pose_period:
                    last_pose = now
                    self._publish_pose()
                if now - last_presence >= presence_period:
                    last_presence = now
                    self._publish_presence()
                time.sleep(0.001)
        finally:
            try:
                self.motors.stop()
            except Exception:
                pass
            self.close()
            print("Rosie run stopped.", file=sys.stderr)
        return 0

    def close(self) -> None:
        for obj in (self.motors, self.encoders, self.imu):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        try:
            self.session.close()
        except Exception:
            pass


def dry_run_report(cfg: RobotConfig) -> str:
    from rosie.run.drivers import probe_drivers

    lines = [
        f"platform: {cfg.platform}",
        f"robot:    {cfg.robot}",
        f"fleet:    {cfg.fleet or '—'}",
        f"connect:  {cfg.connect}",
        f"base:     {(cfg.raw.get('base') or {}).get('type', 'diff_drive')}",
    ]
    lines.append("hardware:")
    for line in describe_hardware(cfg):
        lines.append(f"  {line}")
    lines.append("probe:")
    for line in probe_drivers(cfg):
        lines.append(f"  {line}")
    return "\n".join(lines)


def run_from_config(
    cfg: RobotConfig,
    *,
    robot: str | None = None,
    fleet: str | None = None,
    connect: str | None = None,
    dry_run: bool = False,
    preflight: bool = True,
) -> int:
    from rosie.run.drivers import probe_drivers

    if cfg.platform != "linux":
        raise ValueError(
            f"rosie run requires platform: linux (got {cfg.platform!r}). "
            "MCU robots use `rosie mcu flash`."
        )
    if dry_run:
        print(dry_run_report(cfg))
        return 0

    if preflight:
        print("preflight:", file=sys.stderr)
        for line in probe_drivers(cfg):
            print(f"  {line}", file=sys.stderr)

    motors = build_motors(cfg)
    encoders = build_encoders(cfg)
    imu = build_imu(cfg)
    try:
        # Quick session open check
        rt = MobileBaseRuntime(
            cfg,
            motors=motors,
            encoders=encoders,
            imu=imu,
            robot=robot,
            fleet=fleet,
            connect=connect,
        )
    except Exception:
        for obj in (motors, encoders, imu):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        raise
    return rt.run()
