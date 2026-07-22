"""Planar goto controller (mirrors firmware MobileBase::navigate_)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rosie.run.kinematics import Pose2D


@dataclass
class GotoGains:
    kp_linear: float = 0.8
    kp_angular: float = 1.5
    v_max: float = 0.35
    w_max: float = 1.5
    pos_tolerance: float = 0.025
    approach_dist: float = 0.20
    align_tol: float = 0.52


def navigate_step(
    pose: Pose2D,
    target_x: float,
    target_y: float,
    gains: GotoGains,
) -> tuple[float, float] | None:
    """Return body twist ``(v, w)`` or ``None`` if arrived."""
    dx = target_x - pose.x
    dy = target_y - pose.y
    distance = math.hypot(dx, dy)
    if distance < gains.pos_tolerance:
        return None

    target_heading = math.atan2(dy, dx)
    heading_err = target_heading - pose.theta
    while heading_err > math.pi:
        heading_err -= 2.0 * math.pi
    while heading_err < -math.pi:
        heading_err += 2.0 * math.pi

    if distance < gains.approach_dist and abs(heading_err) > math.pi * 0.5:
        return None

    v = gains.kp_linear * distance
    w = gains.kp_angular * heading_err
    if distance < gains.approach_dist:
        w *= distance / gains.approach_dist

    gate = 1.0 - (abs(heading_err) / gains.align_tol)
    if gate < 0.0:
        gate = 0.0
    v *= gate
    if v < 0:
        v = 0.0

    v = min(v, gains.v_max)
    w = max(-gains.w_max, min(gains.w_max, w))
    return v, w
