"""Pure goto helpers for the ROS 2 agent (no rclpy)."""

from __future__ import annotations

# action_msgs/GoalStatus values (keep numeric so tests need no ROS).
STATUS_SUCCEEDED = 4
STATUS_CANCELED = 5
STATUS_ABORTED = 6

ACCEPT = "accept"
IGNORE_DUPLICATE = "ignore_duplicate"
IGNORE_STALE = "ignore_stale"


def arbitrate_goto(
    navigating: bool,
    active_id: int | None,
    incoming_id: int | None,
) -> str:
    """Decide whether an incoming goto should replace the active goal.

    Matches native MobileBase: while navigating, an equal ``goal_id`` is a
    duplicate and a lower id is stale. Idle (or a missing id) accepts.
    """
    if not navigating or incoming_id is None or active_id is None:
        return ACCEPT
    if incoming_id == active_id:
        return IGNORE_DUPLICATE
    if incoming_id < active_id:
        return IGNORE_STALE
    return ACCEPT


def rosie_nav_status(
    nav2_status: int | str,
    *,
    canceled_by_host: bool = False,
) -> str:
    """Map a Nav2 / action GoalStatus onto Rosie ``nav_result.status``."""
    if canceled_by_host:
        return "canceled"
    if nav2_status in (STATUS_SUCCEEDED, "STATUS_SUCCEEDED", "succeeded"):
        return "succeeded"
    if nav2_status in (STATUS_CANCELED, "STATUS_CANCELED", "canceled"):
        return "canceled"
    return "aborted"
