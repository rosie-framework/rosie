"""Standard relative topic names.

Pass these to ``Session.publish`` / ``subscribe_*``; the session's robot
(and optional fleet) prefixes them. A leading ``/`` makes a name absolute
(not prefixed). Fleet-scoped topics use ``Session.publish_fleet`` /
``resolve_fleet_name`` → ``{fleet}/_fleet/...``.
"""

from __future__ import annotations

POSE = "pose"
LOG = "log"
CMD_VEL = "cmd_vel"
GOTO = "goto"
NAV_RESULT = "nav_result"
CMD = "cmd"
CAMERA_COMPRESSED = "camera/compressed"
PRESENCE = "presence"
CONTROL = "control"
ENCODERS = "encoders"
IMU = "imu"


def range_topic(sensor_id: str) -> str:
    """Relative topic for a named range sensor: ``range/<id>``."""
    sid = str(sensor_id).strip()
    if not sid:
        raise ValueError("range sensor id must be non-empty")
    return f"range/{sid}"
