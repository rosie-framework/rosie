"""NavigateToPose over the Zenoh queries the DDS bridge exposes.

The bridge maps an action to queryables. Payloads are CDR. The request
attachment is the CycloneDDS client header (``rqh`` + 8 byte client id +
8 byte sequence + endian flag) that ``rmw_cyclonedds`` expects.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from .codec import (
    CANCEL_GOAL_REQUEST,
    CANCEL_GOAL_RESPONSE,
    GET_RESULT_REQUEST,
    GET_RESULT_RESPONSE,
    SEND_GOAL_REQUEST,
    SEND_GOAL_RESPONSE,
    encode,
    decode,
)
from .keys import action_key, fleet_namespace
from .pose import quat_from_yaw

# action_msgs/msg/GoalStatus
STATUS_SUCCEEDED = 4
STATUS_CANCELED = 5
STATUS_ABORTED = 6

_ATTACHMENT_KEY = b"rqh"


def request_attachment(client_id: bytes, seq: int) -> bytes:
    """Flat attachment the bridge reads back with ``ZBytes::to_bytes``."""
    if len(client_id) != 8:
        raise ValueError("client id must be 8 bytes")
    return _ATTACHMENT_KEY + client_id + int(seq).to_bytes(8, "little") + b"\x01"


class NavigateToPoseClient:
    """Send, wait, and cancel one robot's NavigateToPose action."""

    def __init__(
        self,
        session: Any,
        *,
        fleet: str,
        robot: str,
        action: str = "/navigate_to_pose",
        frame_id: str = "map",
        distro: str = "jazzy",
        transport: str = "bridge",
    ) -> None:
        if str(transport).lower() not in ("bridge", ""):
            raise NotImplementedError(
                "NavigateToPose from the laptop is implemented for "
                "zenoh-bridge-ros2dds. rmw_zenoh uses a different key layout; "
                "keep the bridge on this robot, or switch the whole robot to "
                "rmw_zenoh and drive Nav2 on the robot itself."
            )
        self.session = session
        self.distro = distro
        self.frame_id = frame_id
        namespace = fleet_namespace(fleet, robot)
        self.send_key = action_key(namespace, action, "send_goal")
        self.result_key = action_key(namespace, action, "get_result")
        self.cancel_key = action_key(namespace, action, "cancel_goal")
        self._client_id = os.urandom(8)
        self._seq = 0
        self._lock = threading.Lock()

    def _next_attachment(self) -> bytes:
        with self._lock:
            self._seq += 1
            seq = self._seq
        return request_attachment(self._client_id, seq)

    def send_goal(
        self,
        x: float,
        y: float,
        *,
        yaw: float = 0.0,
        goal_id: bytes | None = None,
        behavior_tree: str = "",
        timeout_s: float = 5.0,
    ) -> bytes:
        """Ask Nav2 to accept a pose. Returns the 16-byte goal id.

        Raises ``RuntimeError`` when the server rejects the goal or does not
        answer.
        """
        gid = goal_id if goal_id is not None else uuid.uuid4().bytes
        if len(gid) != 16:
            raise ValueError("goal id must be 16 bytes")
        payload = encode(
            SEND_GOAL_REQUEST,
            {
                "goal_id": {"uuid": gid},
                "goal": {
                    "pose": {
                        "header": {"frame_id": self.frame_id},
                        "pose": {
                            "position": {"x": float(x), "y": float(y), "z": 0.0},
                            "orientation": quat_from_yaw(yaw),
                        },
                    },
                    "behavior_tree": behavior_tree,
                },
            },
            distro=self.distro,
        )
        replies = self.session.query(
            self.send_key,
            payload=payload,
            attachment=self._next_attachment(),
            timeout_s=timeout_s,
        )
        if not replies:
            raise RuntimeError(f"no reply from {self.send_key}")
        msg = decode(SEND_GOAL_RESPONSE, replies[0], distro=self.distro)
        if not msg.get("accepted"):
            raise RuntimeError("NavigateToPose rejected the goal")
        return gid

    def wait_result(self, goal_id: bytes, *, timeout_s: float = 120.0) -> dict[str, Any]:
        """Block until Nav2 finishes ``goal_id``. ``status`` is GoalStatus."""
        payload = encode(
            GET_RESULT_REQUEST,
            {"goal_id": {"uuid": goal_id}},
            distro=self.distro,
        )
        replies = self.session.query(
            self.result_key,
            payload=payload,
            attachment=self._next_attachment(),
            timeout_s=timeout_s,
        )
        if not replies:
            raise TimeoutError(f"no result from {self.result_key} within {timeout_s}s")
        return decode(GET_RESULT_RESPONSE, replies[0], distro=self.distro)

    def cancel(self, goal_id: bytes, *, timeout_s: float = 5.0) -> dict[str, Any]:
        payload = encode(
            CANCEL_GOAL_REQUEST,
            {
                "goal_info": {
                    "goal_id": {"uuid": goal_id},
                    "stamp": _now_stamp(),
                }
            },
            distro=self.distro,
        )
        replies = self.session.query(
            self.cancel_key,
            payload=payload,
            attachment=self._next_attachment(),
            timeout_s=timeout_s,
        )
        if not replies:
            return {"return_code": -1, "goals_canceling": []}
        return decode(CANCEL_GOAL_RESPONSE, replies[0], distro=self.distro)


def _now_stamp() -> dict[str, int]:
    seconds = time.time()
    sec = int(seconds)
    return {"sec": sec, "nanosec": int(round((seconds - sec) * 1e9))}


def nav_status_name(status: int | str, *, canceled_by_host: bool = False) -> str:
    """Map ``action_msgs/GoalStatus`` onto the strings Rosie prints."""
    if canceled_by_host:
        return "canceled"
    if status in (STATUS_SUCCEEDED, "STATUS_SUCCEEDED", "succeeded"):
        return "succeeded"
    if status in (STATUS_CANCELED, "STATUS_CANCELED", "canceled"):
        return "canceled"
    return "aborted"
