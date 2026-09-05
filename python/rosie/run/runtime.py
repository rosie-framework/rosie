"""MobileBase-equivalent control loop for Linux (``rosie run``)."""

from __future__ import annotations

import math
import signal
import sys
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from rosie import topics
from rosie.run.drivers import (
    CameraSource,
    EncoderReader,
    ImuReader,
    MotorDriver,
    RangeMeta,
    RangeReader,
    build_camera,
    build_encoders,
    build_imu,
    build_motors,
    build_range_sensors,
    describe_hardware,
)
from rosie.run.goto import GotoGains, navigate_step
from rosie.run.kinematics import DiffDriveGeometry, DiffDriveKinematics, DiffDriveTeleop
from rosie.run.range_filter import MedianWindow
from rosie.run.velocity import PidVelocityController, VelocityGains
from rosie.messages import encode_json
from rosie.robot_config import RobotConfig
from rosie.session import Qos, Session


class DriveMode(str, Enum):
    IDLE = "idle"
    MANUAL = "manual"
    AUTO = "auto"


CmdHandler = Callable[[Any], None]


class MobileBaseRuntime:
    """On-robot loop: cmd_vel / goto / cmd → motors; pose / presence / nav_result out."""

    def __init__(
        self,
        cfg: RobotConfig,
        *,
        motors: MotorDriver,
        encoders: EncoderReader | None = None,
        imu: ImuReader | None = None,
        camera: CameraSource | None = None,
        range_sensors: list[tuple[str, RangeReader, RangeMeta]] | None = None,
        robot: str | None = None,
        fleet: str | None = None,
        connect: str | None = None,
        open_session: bool = True,
    ) -> None:
        self.cfg = cfg
        self.motors = motors
        self.encoders = encoders
        self.imu = imu
        self.camera = camera
        self._range_sensors: list[tuple[str, RangeReader, RangeMeta]] = list(
            range_sensors or []
        )
        self._range_filters: dict[str, MedianWindow] = {
            sid: MedianWindow() for sid, _r, _m in self._range_sensors
        }
        self._range_last: dict[str, dict[str, Any]] = {
            sid: {
                "range": 0.0,
                "range_median": 0.0,
                "ok": False,
            }
            for sid, _r, _m in self._range_sensors
        }
        self._raw = cfg.raw
        control = self._raw.get("control") or {}
        teleop = control.get("teleop") or {}
        base = self._raw.get("base") or {}
        self.kinematics = DiffDriveKinematics(
            DiffDriveGeometry(
                wheel_diameter=float(base.get("wheel_diameter", 0.068)),
                wheel_base=float(base.get("wheel_base", 0.13)),
                ticks_per_rev=float(base.get("ticks_per_rev", 1440)),
            ),
            DiffDriveTeleop(v_full=float(teleop.get("v_full", 1.0))),
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
        self.control_hz = float(control.get("control_hz", 5))
        enc_cfg = self._raw.get("encoders") or {}
        imu_cfg = self._raw.get("imu") or {}
        cam_cfg = self._raw.get("camera") or {}
        self.encoders_hz = float(enc_cfg.get("pub_hz", 0) or 0)
        self.imu_hz = float(imu_cfg.get("pub_hz", 0) or 0)
        self.camera_hz = float(cam_cfg.get("pub_hz", 2) or 2)
        self._camera_enabled = bool(cam_cfg.get("enable_default", True))
        self._camera_stop = threading.Event()
        self._camera_thread: threading.Thread | None = None

        # Optional inner-loop PID (mirrors DiffDriveStack when control.velocity present).
        velocity = control.get("velocity")
        self.velocity: PidVelocityController | None = None
        if isinstance(velocity, dict):
            self.velocity = PidVelocityController(
                VelocityGains(
                    kp=float(velocity.get("kp", 0.0)),
                    ki=float(velocity.get("ki", 0.0)),
                    kd=float(velocity.get("kd", 0.0)),
                    i_clamp=float(velocity.get("i_clamp", 0.5)),
                )
            )

        self._lock = threading.Lock()
        self._cmd_v = 0.0
        self._cmd_w = 0.0
        self._last_cmd_vel_t = 0.0
        self._stop_t = 0.0
        self._zero_t = 0.0
        self._goto_t = 0.0
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
        self._last_enc_left = 0
        self._last_enc_right = 0
        self._last_enc_valid = False
        self._last_accel = (0.0, 0.0, 0.0)
        self._last_gyro = (0.0, 0.0, 0.0)
        self._last_imu_ok = False
        # Hardware presence (IMU constructed), not per-sample validity.
        self._imu_hw_ok = imu is not None
        self._last_target_vel: list[float] = []
        self._last_meas_vel: list[float] = []
        self._cmd_handlers: dict[str, CmdHandler] = {}

        self.session: Session | None = None
        if open_session:
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
        else:
            # Test / offline: no Zenoh session.
            pass

    def on_cmd(self, op: str, handler: CmdHandler) -> None:
        """Register a custom ``cmd`` op handler (value from the message)."""
        self._cmd_handlers[str(op)] = handler

    def _reset_velocity(self) -> None:
        if self.velocity is not None:
            self.velocity.reset()

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
            self._goto_t = time.monotonic()
            self._goto_req = True

    def _on_cmd(self, msg: dict) -> None:
        op = str(msg.get("op", ""))
        value = msg.get("value")
        if op == "stop":
            with self._lock:
                self._stop_req = True
                self._stop_t = time.monotonic()
            return
        if op == "zero":
            with self._lock:
                self._zero_req = True
                self._zero_t = time.monotonic()
            return
        if op == "set_gains":
            self._handle_set_gains(value)
            return
        if op == "get_gains":
            self._handle_get_gains()
            return
        if op == "heading_source":
            self._handle_heading_source(value)
            return
        if op == "camera_enable":
            self._handle_camera_enable(value)
            return
        handler = self._cmd_handlers.get(op)
        if handler is not None:
            handler(value)

    def _handle_set_gains(self, value: Any) -> None:
        if self.velocity is None:
            self._log("warn", "set_gains: no velocity controller attached")
            return
        if not isinstance(value, dict):
            self._log("warn", "set_gains: value must be a JSON object")
            return
        g = self.velocity.gains()
        if "kp" in value:
            g.kp = float(value["kp"])
        if "ki" in value:
            g.ki = float(value["ki"])
        if "kd" in value:
            g.kd = float(value["kd"])
        if "i_clamp" in value:
            g.i_clamp = float(value["i_clamp"])
        self.velocity.configure(g)
        self._log(
            "info",
            f"Gains set: kp={g.kp} ki={g.ki} kd={g.kd} i_clamp={g.i_clamp}",
        )
        self._publish_control()

    def _handle_get_gains(self) -> None:
        if self.velocity is None:
            self._log("warn", "get_gains: no velocity controller attached")
            return
        g = self.velocity.gains()
        self._publish_control()
        self._log(
            "info",
            f"Gains: kp={g.kp} ki={g.ki} kd={g.kd} i_clamp={g.i_clamp}",
        )

    def _handle_heading_source(self, value: Any) -> None:
        if self.imu is None:
            self._log("warn", "heading_source: no IMU")
            return
        if value is None:
            next_use = not self.kinematics.use_imu_heading
        elif isinstance(value, bool):
            next_use = value
        else:
            try:
                next_use = int(value) != 0
            except (TypeError, ValueError):
                next_use = bool(value)
        self.kinematics.use_imu_heading = next_use
        src = "imu" if next_use else "encoders"
        self._log("info", f"Heading source: {src}")

    def _handle_camera_enable(self, value: Any) -> None:
        if self.camera is None:
            self._log("warn", "camera_enable: no camera attached")
            return
        if value is None:
            enabled = not self._camera_enabled
        elif isinstance(value, bool):
            enabled = value
        else:
            try:
                enabled = int(value) != 0
            except (TypeError, ValueError):
                enabled = bool(value)
        self._camera_enabled = enabled
        self._log("info", f"Camera {'enabled' if enabled else 'disabled'}")

    def _publish_pose(self) -> None:
        if self.session is None:
            return
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
            "imu_ok": self._imu_hw_ok,
            "imu_heading": self._imu_hw_ok and self.kinematics.use_imu_heading,
        }
        if self._navigating:
            doc["goal_id"] = self._active_goal_id
        self.session.publish(topics.POSE, encode_json(doc))

    def _publish_presence(self) -> None:
        if self.session is None:
            return
        doc: dict[str, Any] = {
            "robot_id": self.session.robot,
            "status": "ready",
        }
        if self.session.fleet:
            doc["fleet_id"] = self.session.fleet
        self.session.publish(topics.PRESENCE, encode_json(doc))

    def _publish_control(self) -> None:
        if self.session is None or self.velocity is None:
            return
        g = self.velocity.gains()
        self.session.publish(
            topics.CONTROL,
            encode_json(
                {
                    "kp": g.kp,
                    "ki": g.ki,
                    "kd": g.kd,
                    "i_clamp": g.i_clamp,
                    "mode": self._mode.value,
                    "target_vel": list(self._last_target_vel),
                    "meas_vel": list(self._last_meas_vel),
                }
            ),
        )

    def _publish_encoders(self) -> None:
        if self.session is None or not self._last_enc_valid:
            return
        self.session.publish(
            topics.ENCODERS,
            encode_json(
                {
                    "left": self._last_enc_left,
                    "right": self._last_enc_right,
                }
            ),
        )

    def _publish_imu(self) -> None:
        if self.session is None:
            return
        ax, ay, az = self._last_accel
        gx, gy, gz = self._last_gyro
        self.session.publish(
            topics.IMU,
            encode_json(
                {
                    "accel_x": ax if self._last_imu_ok else 0.0,
                    "accel_y": ay if self._last_imu_ok else 0.0,
                    "accel_z": az if self._last_imu_ok else 0.0,
                    "gyro_x": gx if self._last_imu_ok else 0.0,
                    "gyro_y": gy if self._last_imu_ok else 0.0,
                    "gyro_z": gz if self._last_imu_ok else 0.0,
                    "ok": self._last_imu_ok,
                }
            ),
        )

    def _publish_range(self, sensor_id: str, reader: RangeReader, meta: RangeMeta) -> None:
        if self.session is None:
            return
        raw = reader.read_range()
        last = self._range_last[sensor_id]
        if raw is not None:
            last["range"] = float(raw)
            last["range_median"] = self._range_filters[sensor_id].push(float(raw))
            last["ok"] = True
        else:
            last["ok"] = False
        self.session.publish(
            topics.range_topic(sensor_id),
            encode_json(
                {
                    "id": sensor_id,
                    "range": last["range"],
                    "range_median": last["range_median"],
                    "min_range": meta.min_range,
                    "max_range": meta.max_range,
                    "ok": last["ok"],
                }
            ),
        )

    def _publish_nav_result(self, status: str) -> None:
        if self.session is None:
            return
        p = self.kinematics.pose()
        # COMMAND: host uses BLOCK; same class on the wire for nav_result.
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
            qos=Qos.COMMAND,
        )

    def _log(self, level: str, msg: str) -> None:
        print(f"LOG[{level}] {msg}", file=sys.stderr)
        if self.session is None:
            return
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
        self._reset_velocity()

    def _drive(self, v: float, w: float) -> None:
        self.kinematics.set_commanded_twist(v, w)
        ff = self.kinematics.twist_to_channels(v, w)
        target = self.kinematics.twist_to_wheel_vel(v, w)
        meas = self.kinematics.wheel_velocities()
        self._last_target_vel = list(target)
        self._last_meas_vel = list(meas)
        dt = self.dt_ms / 1000.0
        if self.velocity is not None:
            out = self.velocity.update(ff, target, meas, dt)
            self.motors.set_channels(out)
        else:
            self.motors.set_channels(ff)

    def _invoke_zero_hooks(self) -> None:
        if self.encoders is not None:
            zero_fn = getattr(self.encoders, "zero", None)
            if callable(zero_fn):
                try:
                    zero_fn()
                except Exception as e:
                    self._log("warn", f"encoders.zero failed: {e}")
        if self.imu is not None:
            recal = getattr(self.imu, "recalibrate", None)
            if callable(recal):
                try:
                    recal()
                except Exception as e:
                    self._log("warn", f"imu.recalibrate failed: {e}")

    def tick(self) -> None:
        dt = self.dt_ms / 1000.0
        ticks = None
        if self.encoders is not None:
            ticks = self.encoders.read_ticks()
            self._last_enc_left = int(ticks[0])
            self._last_enc_right = int(ticks[1])
            self._last_enc_valid = True
        else:
            self._last_enc_valid = False
        yaw_rate = None
        if self.imu is not None:
            sample = None
            read_sample = getattr(self.imu, "read_sample", None)
            if callable(read_sample):
                sample = read_sample()
            if sample is not None:
                self._last_accel = (float(sample[0]), float(sample[1]), float(sample[2]))
                self._last_gyro = (float(sample[3]), float(sample[4]), float(sample[5]))
                self._last_imu_ok = True
                yaw_rate = float(sample[5])
            else:
                yaw_rate = self.imu.read_yaw_rate()
                self._last_imu_ok = yaw_rate is not None
                if yaw_rate is not None:
                    self._last_gyro = (0.0, 0.0, float(yaw_rate))
        else:
            self._last_imu_ok = False
        self.kinematics.update_odometry(ticks, dt, yaw_rate)

        with self._lock:
            stop_req = self._stop_req
            zero_req = self._zero_req
            goto_req = self._goto_req
            cmd_vel_seen = self._cmd_vel_seen
            cmd_v, cmd_w = self._cmd_v, self._cmd_w
            last_cmd_t = self._last_cmd_vel_t
            stop_t = self._stop_t
            zero_t = self._zero_t
            goto_t = self._goto_t
            goto_x, goto_y = self._goto_x, self._goto_y
            goto_has_id = self._goto_has_id
            goto_goal_id = self._goto_goal_id
            self._stop_req = False
            self._zero_req = False
            self._goto_req = False
            self._cmd_vel_seen = False

        prev_mode = self._mode

        if stop_req:
            if self._navigating:
                self._end_nav("canceled")
                self._log("info", "Stopped.")
            else:
                self._mode = DriveMode.IDLE
                self.motors.stop()
                self.kinematics.set_commanded_twist(0.0, 0.0)
                self._reset_velocity()
                self._log("info", "Stopped.")

        if zero_req:
            if self._navigating:
                self._end_nav("canceled")
            self.kinematics.zero_pose()
            self._invoke_zero_hooks()
            self._mode = DriveMode.IDLE
            self.motors.stop()
            self._reset_velocity()
            self._log("info", "Pose zeroed.")

        if goto_req:
            if goto_t < stop_t or goto_t < zero_t:
                pass  # superseded by newer stop/zero
            elif self._navigating and goto_has_id:
                if goto_goal_id == self._active_goal_id:
                    pass  # duplicate — keep driving
                elif goto_goal_id < self._active_goal_id:
                    self._log(
                        "warn",
                        f"Ignoring stale goto goal_id={goto_goal_id} "
                        f"(active={self._active_goal_id})",
                    )
                else:
                    self._end_nav("canceled")
                    self._target_x = goto_x
                    self._target_y = goto_y
                    self._active_goal_id = goto_goal_id
                    if self._active_goal_id >= self._next_goal_id:
                        self._next_goal_id = self._active_goal_id + 1
                    self._navigating = True
                    self._mode = DriveMode.AUTO
                    self._log(
                        "info",
                        f"New target: ({goto_x:.3f}, {goto_y:.3f}) m "
                        f"goal_id={self._active_goal_id}",
                    )
            else:
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

        # Enter Manual only if cmd_vel arrived after the latest stop/zero.
        if cmd_vel_seen and last_cmd_t > stop_t and last_cmd_t > zero_t:
            if self._navigating:
                self._end_nav("canceled")
            self._mode = DriveMode.MANUAL

        # Reset PID on Manual ↔ Auto transitions (mirrors firmware).
        if (
            (prev_mode == DriveMode.MANUAL and self._mode == DriveMode.AUTO)
            or (prev_mode == DriveMode.AUTO and self._mode == DriveMode.MANUAL)
        ):
            self._reset_velocity()

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
                self._reset_velocity()
                self._mode = DriveMode.IDLE
                self._log("warn", "Teleop deadman timeout.")
            else:
                self._drive(cmd_v, cmd_w)

    def _camera_loop(self) -> None:
        """Daemon thread: capture JPEG and publish at camera.pub_hz."""
        period = 1.0 / self.camera_hz if self.camera_hz > 0.1 else 0.5
        while not self._camera_stop.is_set():
            if not self._camera_enabled or self.camera is None or self.session is None:
                if self._camera_stop.wait(0.05):
                    break
                continue
            t0 = time.monotonic()
            try:
                jpeg = self.camera.read_jpeg()
                if jpeg:
                    self.session.publish(
                        topics.CAMERA_COMPRESSED, jpeg, qos=Qos.BULK
                    )
            except Exception as e:
                self._log("warn", f"camera capture failed: {e}")
            elapsed = time.monotonic() - t0
            remaining = period - elapsed
            if remaining > 0 and self._camera_stop.wait(remaining):
                break

    def _start_camera_thread(self) -> None:
        if self.camera is None or self.session is None:
            return
        if self._camera_thread is not None and self._camera_thread.is_alive():
            return
        self._camera_stop.clear()
        self._camera_thread = threading.Thread(
            target=self._camera_loop,
            name="rosie-camera",
            daemon=True,
        )
        self._camera_thread.start()

    def _stop_camera_thread(self) -> None:
        self._camera_stop.set()
        t = self._camera_thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._camera_thread = None

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
        self._start_camera_thread()
        last_tick = time.monotonic()
        last_pose = 0.0
        last_presence = 0.0
        last_control = 0.0
        last_encoders = 0.0
        last_imu = 0.0
        last_range: dict[str, float] = {sid: 0.0 for sid, _r, _m in self._range_sensors}
        pose_period = 1.0 / self.pose_hz if self.pose_hz > 0.1 else 0.05
        presence_period = (
            1.0 / self.presence_hz if self.presence_hz > 0.1 else 1.0
        )
        control_period = (
            1.0 / self.control_hz if self.control_hz > 0.1 else 0.2
        )
        encoders_period = (
            1.0 / self.encoders_hz if self.encoders_hz > 0.1 else 0.0
        )
        imu_period = 1.0 / self.imu_hz if self.imu_hz > 0.1 else 0.0
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
                if (
                    self.velocity is not None
                    and now - last_control >= control_period
                ):
                    last_control = now
                    self._publish_control()
                if (
                    encoders_period > 0
                    and self.encoders is not None
                    and now - last_encoders >= encoders_period
                ):
                    last_encoders = now
                    self._publish_encoders()
                if (
                    imu_period > 0
                    and self.imu is not None
                    and now - last_imu >= imu_period
                ):
                    last_imu = now
                    self._publish_imu()
                for sid, reader, meta in self._range_sensors:
                    hz = meta.pub_hz
                    if hz <= 0.1:
                        continue
                    period = 1.0 / hz
                    if now - last_range[sid] >= period:
                        last_range[sid] = now
                        self._publish_range(sid, reader, meta)
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
        self._stop_camera_thread()
        for obj in (self.motors, self.encoders, self.imu, self.camera):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        for _sid, reader, _meta in self._range_sensors:
            try:
                reader.close()
            except Exception:
                pass
        if self.session is not None:
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
    camera = None
    if cfg.raw.get("camera"):
        try:
            camera = build_camera(cfg)
        except Exception as e:
            print(
                f"warn: camera init failed ({e}); continuing without camera",
                file=sys.stderr,
            )
            camera = None
    range_sensors: list = []
    if cfg.raw.get("range"):
        try:
            range_sensors = build_range_sensors(cfg)
        except Exception as e:
            print(
                f"warn: range init failed ({e}); continuing without range",
                file=sys.stderr,
            )
            range_sensors = []
    try:
        # Quick session open check
        rt = MobileBaseRuntime(
            cfg,
            motors=motors,
            encoders=encoders,
            imu=imu,
            camera=camera,
            range_sensors=range_sensors,
            robot=robot,
            fleet=fleet,
            connect=connect,
        )
    except Exception:
        for obj in (motors, encoders, imu, camera):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        for _sid, reader, _meta in range_sensors:
            try:
                reader.close()
            except Exception:
                pass
        raise
    return rt.run()
