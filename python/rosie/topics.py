"""Relative names for the JSON fleet plane.

Robot data is a ROS topic named by the robot's profile, not one of these
constants. Pass these to ``Session.publish`` / ``subscribe_*``; the session
prefixes ``{fleet}/{robot}/``. Fleet-scoped topics use
``Session.publish_fleet`` → ``{fleet}/_fleet/...``.
"""

from __future__ import annotations

PRESENCE = "presence"
ROUTER = "router"
ESTOP = "estop"
# Reserved so a link emulator can record conditions in the same bag as the robot.
LINK = "link"
CAMERA_COMPRESSED = "camera/compressed"
