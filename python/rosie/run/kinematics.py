"""Differential-drive kinematics + odometry (mirrors firmware)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Pose2D:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0


@dataclass
class DiffDriveGeometry:
    wheel_diameter: float = 0.068
    wheel_base: float = 0.13
    ticks_per_rev: float = 1440.0


@dataclass
class DiffDriveTeleop:
    """Open-loop feedforward: channel = saturate(wheel_vel / v_full)."""

    v_full: float = 1.0


class DiffDriveKinematics:
    """Two-channel diff-drive: twist → motor channels + encoder odometry."""

    def __init__(
        self,
        geom: DiffDriveGeometry | None = None,
        teleop: DiffDriveTeleop | None = None,
        *,
        imu_enc_fallback_ratio: float = 0.25,
    ) -> None:
        self.geom = geom or DiffDriveGeometry()
        self.teleop = teleop or DiffDriveTeleop()
        self.imu_enc_fallback_ratio = imu_enc_fallback_ratio
        self._pose = Pose2D()
        self._prev_left = 0
        self._prev_right = 0
        self._have_prev = False
        self.use_imu_heading = True
        self._wheel_vel = [0.0, 0.0]
        # Last commanded body twist (for no-encoder integration)
        self._last_v = 0.0
        self._last_w = 0.0

    @property
    def channel_count(self) -> int:
        return 2

    def pose(self) -> Pose2D:
        return Pose2D(self._pose.x, self._pose.y, self._pose.theta)

    def zero_pose(self) -> None:
        self._pose = Pose2D()
        self._have_prev = False
        self._prev_left = 0
        self._prev_right = 0
        self._wheel_vel = [0.0, 0.0]

    def twist_to_channels(self, v: float, w: float) -> list[float]:
        left_v, right_v = self.twist_to_wheel_vel(v, w)
        v_full = self.teleop.v_full
        if v_full < 1e-6:
            v_full = 1e-6
        left = left_v / v_full
        right = right_v / v_full
        return [max(-1.0, min(1.0, left)), max(-1.0, min(1.0, right))]

    def twist_to_wheel_vel(self, v: float, w: float) -> list[float]:
        half_l = self.geom.wheel_base * 0.5
        return [v - w * half_l, v + w * half_l]

    def wheel_velocities(self) -> list[float]:
        return list(self._wheel_vel)

    def set_commanded_twist(self, v: float, w: float) -> None:
        self._last_v = float(v)
        self._last_w = float(w)

    def update_odometry(
        self,
        ticks: tuple[int, int] | None,
        dt_s: float,
        yaw_rate_hint: float | None = None,
    ) -> None:
        """Update pose from encoder ticks, or integrate commanded twist if no ticks."""
        if dt_s <= 0.0 or dt_s > 0.2:
            dt_s = 0.02

        if ticks is None:
            self._integrate_commanded(dt_s, yaw_rate_hint)
            return

        left, right = int(ticks[0]), int(ticks[1])
        if not self._have_prev:
            self._prev_left = left
            self._prev_right = right
            self._have_prev = True
            self._wheel_vel = [0.0, 0.0]
            return

        d_l = left - self._prev_left
        d_r = right - self._prev_right
        self._prev_left = left
        self._prev_right = right

        dist_per_tick = (math.pi * self.geom.wheel_diameter) / self.geom.ticks_per_rev
        d_left = d_l * dist_per_tick
        d_right = d_r * dist_per_tick
        d_center = (d_left + d_right) * 0.5
        d_theta_enc = (d_right - d_left) / self.geom.wheel_base
        self._wheel_vel = [d_left / dt_s, d_right / dt_s]

        d_theta = d_theta_enc
        if (
            self.use_imu_heading
            and yaw_rate_hint is not None
            and not math.isnan(yaw_rate_hint)
        ):
            d_theta_imu = yaw_rate_hint * dt_s
            if abs(d_theta_enc) > 0.005 and abs(d_theta_imu) < (
                self.imu_enc_fallback_ratio * abs(d_theta_enc)
            ):
                d_theta = d_theta_enc
            else:
                d_theta = d_theta_imu

        self._apply_delta(d_center, d_theta)

    def _integrate_commanded(
        self, dt_s: float, yaw_rate_hint: float | None
    ) -> None:
        v, w = self._last_v, self._last_w
        if yaw_rate_hint is not None and not math.isnan(yaw_rate_hint):
            w = yaw_rate_hint
        d_center = v * dt_s
        d_theta = w * dt_s
        half_l = self.geom.wheel_base * 0.5
        self._wheel_vel = [v - w * half_l, v + w * half_l]
        self._apply_delta(d_center, d_theta)

    def _apply_delta(self, d_center: float, d_theta: float) -> None:
        mid = self._pose.theta + d_theta * 0.5
        self._pose.x += d_center * math.cos(mid)
        self._pose.y += d_center * math.sin(mid)
        self._pose.theta += d_theta
        while self._pose.theta > math.pi:
            self._pose.theta -= 2.0 * math.pi
        while self._pose.theta < -math.pi:
            self._pose.theta += 2.0 * math.pi
