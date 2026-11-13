"""Pull a planar pose out of the ROS messages a profile can name."""

from __future__ import annotations

import math
from typing import Any


def yaw_from_quat(x: float, y: float, z: float, w: float) -> float:
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny, cosy)


def quat_from_yaw(yaw: float) -> dict[str, float]:
    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(yaw / 2.0),
        "w": math.cos(yaw / 2.0),
    }


def _position_and_quat(type_name: str, msg: dict[str, Any]) -> tuple[dict, dict]:
    if type_name == "nav_msgs/msg/Odometry":
        pose = msg["pose"]["pose"]
    elif type_name == "geometry_msgs/msg/PoseWithCovarianceStamped":
        pose = msg["pose"]["pose"]
    elif type_name == "geometry_msgs/msg/PoseStamped":
        pose = msg["pose"]
    else:
        raise ValueError(f"no planar pose in {type_name}")
    return pose["position"], pose["orientation"]


def pose_dict(type_name: str, msg: dict[str, Any]) -> dict[str, float]:
    """``x``, ``y`` in meters and ``theta`` in radians."""
    position, quat = _position_and_quat(type_name, msg)
    theta = yaw_from_quat(
        float(quat.get("x") or 0.0),
        float(quat.get("y") or 0.0),
        float(quat.get("z") or 0.0),
        float(quat.get("w") or 0.0),
    )
    return {
        "x": float(position.get("x") or 0.0),
        "y": float(position.get("y") or 0.0),
        "theta": theta,
        "heading_deg": theta * 180.0 / math.pi,
    }


def twist_dict(
    type_name: str,
    v: float,
    w: float,
    *,
    frame_id: str = "base_link",
    stamp_s: float | None = None,
) -> dict[str, Any]:
    """Body for ``Twist`` or ``TwistStamped``."""
    twist = {
        "linear": {"x": float(v), "y": 0.0, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": float(w)},
    }
    if type_name == "geometry_msgs/msg/Twist":
        return twist
    if type_name == "geometry_msgs/msg/TwistStamped":
        import time

        seconds = time.time() if stamp_s is None else float(stamp_s)
        sec = int(seconds)
        nanosec = int(round((seconds - sec) * 1e9))
        return {
            "header": {"stamp": {"sec": sec, "nanosec": nanosec}, "frame_id": frame_id},
            "twist": twist,
        }
    raise ValueError(f"not a velocity type: {type_name}")
