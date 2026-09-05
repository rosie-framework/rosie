"""Tests for Linux velocity PID, gains ops, heading source, and pose fields."""

from __future__ import annotations

from rosie.robot_config import RobotConfig
from rosie.run.drivers import NullMotorDriver
from rosie.run.runtime import DriveMode, MobileBaseRuntime
from rosie.run.velocity import PidVelocityController, VelocityGains


def _runtime(*, velocity: dict | None = None, imu: bool = False) -> MobileBaseRuntime:
    control: dict = {"dt_ms": 20, "teleop": {"timeout_ms": 400}}
    if velocity is not None:
        control["velocity"] = velocity
    raw: dict = {
        "robot": "testbot",
        "fleet": "lab",
        "platform": "linux",
        "network": {"connect": "tcp/127.0.0.1:7447"},
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {"driver": "null"},
        "control": control,
    }
    if imu:
        raw["imu"] = {"chip": "mpu6050", "i2c": {"bus": 1, "addr": 0x68}}
    return MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        imu=_FakeImu() if imu else None,
        open_session=False,
    )


class _FakeImu:
    def read_yaw_rate(self) -> float | None:
        return 0.0

    def close(self) -> None:
        pass

    def recalibrate(self) -> None:
        self.recalibrated = True


class _FakeEncoders:
    def __init__(self) -> None:
        self.ticks = (10, 20)
        self.zeroed = False

    def read_ticks(self) -> tuple[int, int]:
        return self.ticks

    def zero(self) -> None:
        self.zeroed = True
        self.ticks = (0, 0)

    def close(self) -> None:
        pass


def _cpp_pid_step(
    ff: list[float],
    target: list[float],
    meas: list[float],
    gains: VelocityGains,
    *,
    integ: list[float],
    prev_err: list[float],
    have_prev: list[bool],
    dt: float,
) -> list[float]:
    """Reference implementation of firmware PidVelocityController::update."""
    if dt <= 0.0 or dt > 0.2:
        dt = 0.02
    closed = gains.kp != 0.0 or gains.ki != 0.0 or gains.kd != 0.0
    out: list[float] = []
    for i in range(len(ff)):
        u = float(ff[i])
        if closed:
            err = float(target[i]) - float(meas[i])
            integ[i] += err * dt
            ic = gains.i_clamp
            if ic < 0.0:
                ic = 0.0
            if integ[i] > ic:
                integ[i] = ic
            if integ[i] < -ic:
                integ[i] = -ic
            deriv = 0.0
            if have_prev[i]:
                deriv = (err - prev_err[i]) / dt
            prev_err[i] = err
            have_prev[i] = True
            u += gains.kp * err + gains.ki * integ[i] + gains.kd * deriv
        if u > 1.0:
            u = 1.0
        if u < -1.0:
            u = -1.0
        out.append(u)
    return out


def test_zero_gains_passthrough():
    ctrl = PidVelocityController(VelocityGains())
    ff = [0.5, -0.3]
    out = ctrl.update(ff, [1.0, 1.0], [0.0, 0.0], 0.02)
    assert out == ff


def test_zero_gains_clamps_ff():
    ctrl = PidVelocityController(VelocityGains())
    out = ctrl.update([1.5, -2.0], None, None, 0.02)
    assert out == [1.0, -1.0]


def test_nonzero_kp_corrects_toward_target():
    ctrl = PidVelocityController(VelocityGains(kp=0.5))
    out = ctrl.update([0.0, 0.0], [1.0, 0.0], [0.0, 0.0], 0.02)
    assert out[0] == 0.5
    assert out[1] == 0.0


def test_i_clamp_and_negative_clamp():
    ctrl = PidVelocityController(VelocityGains(ki=1.0, i_clamp=0.1))
    for _ in range(20):
        ctrl.update([0.0], [1.0], [0.0], 0.02)
    out = ctrl.update([0.0], [1.0], [0.0], 0.02)
    assert abs(out[0] - 0.1) < 1e-6

    ctrl2 = PidVelocityController(VelocityGains(ki=1.0, i_clamp=-1.0))
    out2 = ctrl2.update([0.0], [1.0], [0.0], 0.02)
    assert out2[0] == 0.0


def test_dt_fallback():
    ctrl = PidVelocityController(VelocityGains(kp=1.0))
    out = ctrl.update([0.0], [1.0], [0.0], -1.0)
    assert out[0] == 1.0


def test_python_matches_cpp_reference_table():
    cases = [
        ([0.2, 0.2], [0.5, 0.5], [0.1, 0.1], VelocityGains(kp=0.4), 0.02),
        ([0.0, 0.0], [1.0, -1.0], [0.0, 0.0], VelocityGains(kp=0.3, ki=0.1, i_clamp=0.5), 0.02),
        ([0.8, -0.8], [0.2, -0.2], [0.5, -0.5], VelocityGains(kp=0.5, kd=0.01), 0.02),
        ([0.0], [0.0], [0.0], VelocityGains(), 0.5),
    ]
    for ff, target, meas, gains, dt in cases:
        py = PidVelocityController(gains)
        integ = [0.0] * 4
        prev = [0.0] * 4
        have = [False] * 4
        for _ in range(2):
            got = py.update(ff, target, meas, dt)
            want = _cpp_pid_step(
                ff, target, meas, gains, integ=integ, prev_err=prev, have_prev=have, dt=dt
            )
            assert len(got) == len(want)
            for a, b in zip(got, want):
                assert abs(a - b) < 1e-9


def test_set_gains_partial_merge_and_reset():
    rt = _runtime(velocity={"kp": 0.1, "ki": 0.2, "kd": 0.3, "i_clamp": 0.5})
    assert rt.velocity is not None
    rt.velocity.update([0.0], [1.0], [0.0], 0.02)
    rt._on_cmd({"op": "set_gains", "value": {"kp": 0.9}})
    g = rt.velocity.gains()
    assert g.kp == 0.9
    assert g.ki == 0.2
    assert g.kd == 0.3
    assert g.i_clamp == 0.5
    out = rt.velocity.update([0.0], [1.0], [0.0], 0.02)
    assert abs(out[0] - (0.9 + 0.004)) < 1e-9


def test_set_gains_without_controller_warns():
    rt = _runtime(velocity=None)
    assert rt.velocity is None
    rt._on_cmd({"op": "set_gains", "value": {"kp": 0.5}})


def test_drive_open_loop_without_velocity_section():
    rt = _runtime(velocity=None)
    rt._drive(0.2, 0.0)
    ff = rt.kinematics.twist_to_channels(0.2, 0.0)
    assert rt.motors.last == ff


def test_drive_uses_pid_when_attached():
    rt = _runtime(velocity={"kp": 0.5, "ki": 0.0, "kd": 0.0})
    rt._drive(0.0, 0.0)
    assert rt.motors.last == [0.0, 0.0]
    assert rt._last_target_vel == [0.0, 0.0]


def test_velocity_reset_on_stop():
    rt = _runtime(velocity={"ki": 1.0, "i_clamp": 0.5})
    assert rt.velocity is not None
    rt.velocity.update([0.0], [1.0], [0.0], 0.02)
    rt._on_cmd_vel({"v": 0.2, "w": 0.0})
    rt.tick()
    assert rt._mode == DriveMode.MANUAL
    rt._on_cmd({"op": "stop"})
    rt.tick()
    assert rt._mode == DriveMode.IDLE
    out = rt.velocity.update([0.0], [1.0], [0.0], 0.02)
    assert abs(out[0] - 0.02) < 1e-9


def test_heading_source_toggle():
    rt = _runtime(imu=True)
    assert rt.kinematics.use_imu_heading is True
    rt._on_cmd({"op": "heading_source", "value": None})
    assert rt.kinematics.use_imu_heading is False
    rt._on_cmd({"op": "heading_source", "value": True})
    assert rt.kinematics.use_imu_heading is True
    rt._on_cmd({"op": "heading_source", "value": 0})
    assert rt.kinematics.use_imu_heading is False


def test_pose_includes_imu_fields():
    rt = _runtime(imu=True)
    p = rt.kinematics.pose()
    assert rt._imu_hw_ok is True
    doc = {
        "imu_ok": rt._imu_hw_ok,
        "imu_heading": rt._imu_hw_ok and rt.kinematics.use_imu_heading,
        "x": p.x,
    }
    assert doc["imu_ok"] is True
    assert doc["imu_heading"] is True
    rt.kinematics.use_imu_heading = False
    assert (rt._imu_hw_ok and rt.kinematics.use_imu_heading) is False


def test_zero_invokes_encoder_and_imu_hooks():
    enc = _FakeEncoders()
    imu = _FakeImu()
    raw = {
        "robot": "testbot",
        "fleet": "lab",
        "platform": "linux",
        "network": {"connect": "tcp/127.0.0.1:7447"},
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {"driver": "null"},
        "control": {"dt_ms": 20, "velocity": {"kp": 0.0}},
    }
    rt = MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        encoders=enc,
        imu=imu,
        open_session=False,
    )
    rt._on_cmd({"op": "zero"})
    rt.tick()
    assert enc.zeroed is True
    assert getattr(imu, "recalibrated", False) is True


def test_custom_on_cmd_handler():
    rt = _runtime()
    seen: list = []
    rt.on_cmd("my_op", lambda v: seen.append(v))
    rt._on_cmd({"op": "my_op", "value": {"x": 1}})
    assert seen == [{"x": 1}]


def test_control_hz_codegen():
    from rosie.robot_config import generate_robot_config_h

    raw = {
        "robot": "car1",
        "fleet": "lab",
        "network": {
            "mode": "softap",
            "ssid": "x",
            "password": "y",
            "connect": "tcp/1.2.3.4:7447",
        },
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {
            "driver": "tb6612",
            "pins": {
                "pwmA": 1,
                "ain1": 2,
                "ain2": 3,
                "pwmB": 4,
                "bin1": 5,
                "bin2": 6,
            },
        },
        "control": {"pose_hz": 20, "presence_hz": 1, "control_hz": 7},
    }
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "static const float ROSIE_CONTROL_HZ = 7.0f;" in hdr
