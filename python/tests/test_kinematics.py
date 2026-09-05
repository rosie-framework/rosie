"""Diff-drive twist → channel feedforward (wheel-space v_full)."""

from __future__ import annotations

from rosie.run.kinematics import DiffDriveGeometry, DiffDriveKinematics, DiffDriveTeleop


def _kin(*, wheel_base: float = 0.13, v_full: float = 1.0) -> DiffDriveKinematics:
    return DiffDriveKinematics(
        DiffDriveGeometry(wheel_diameter=0.065, wheel_base=wheel_base, ticks_per_rev=2340),
        DiffDriveTeleop(v_full=v_full),
    )


def test_straight_is_v_over_v_full():
    kin = _kin(v_full=0.5)
    left, right = kin.twist_to_channels(0.25, 0.0)
    assert abs(left - 0.5) < 1e-9
    assert abs(right - 0.5) < 1e-9


def test_spin_uses_wheel_base():
    kin = _kin(wheel_base=0.13, v_full=0.5)
    # v_l = 0 - w * L/2 = -0.065; v_r = +0.065
    left, right = kin.twist_to_channels(0.0, 1.0)
    assert abs(left - (-0.13)) < 1e-9
    assert abs(right - 0.13) < 1e-9


def test_channels_match_ik_over_v_full():
    kin = _kin(v_full=0.8)
    v, w = 0.2, 0.8
    wheels = kin.twist_to_wheel_vel(v, w)
    ch = kin.twist_to_channels(v, w)
    assert abs(ch[0] - wheels[0] / 0.8) < 1e-9
    assert abs(ch[1] - wheels[1] / 0.8) < 1e-9


def test_channels_saturate():
    kin = _kin(v_full=0.1)
    left, right = kin.twist_to_channels(0.5, 0.0)
    assert left == 1.0
    assert right == 1.0
