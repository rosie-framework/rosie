"""ROS 2 ↔ Rosie bridge backend."""

from __future__ import annotations

import math
import sys
import threading
from typing import TYPE_CHECKING, Any

from rosie import topics
from rosie.agent.goto import ACCEPT, STATUS_ABORTED, arbitrate_goto, rosie_nav_status
from rosie.messages import encode_json
from rosie.session import Qos

if TYPE_CHECKING:
    from rosie.session import Session
    from rosie.agent.config import AgentConfig


_RCLPY_HINT = (
    "rosie agent requires ROS 2 Python bindings (rclpy) on this machine.\n"
    "  1. Source your ROS 2 install (e.g. source /opt/ros/$ROS_DISTRO/setup.bash)\n"
    "  2. Use a venv that can see system packages:\n"
    "       python3 -m venv --system-site-packages ~/rosie-venv\n"
    "       source ~/rosie-venv/bin/activate && pip install rosie-framework\n"
    "  Rosie does not install ROS — it bridges an existing ROS stack."
)

_NAV_SERVER_WAIT_S = 2.0


def require_rclpy() -> Any:
    """Import rclpy or raise ImportError with install hints."""
    try:
        import rclpy
    except ImportError as e:
        raise ImportError(_RCLPY_HINT) from e
    return rclpy


def yaw_from_quat(x: float, y: float, z: float, w: float) -> float:
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny, cosy)


class Ros2Bridge:
    """Map Rosie cmd_vel / goto / pose onto ROS /cmd_vel, /odom, and Nav2."""

    def __init__(self, session: Session, cfg: AgentConfig) -> None:
        self.session = session
        self.cfg = cfg
        self._rclpy = require_rclpy()
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry

        self._Twist = Twist
        self._Odometry = Odometry
        self._PoseCov = None
        self._node: Any = None
        self._cmd_pub: Any = None
        self._nav_client: Any = None
        self._NavigateToPose: Any = None
        self._lock = threading.Lock()
        self._navigating = False
        self._active_goal_id = 0
        self._next_goal_id = 1
        self._target_x = 0.0
        self._target_y = 0.0
        self._pose_x = 0.0
        self._pose_y = 0.0
        self._pose_yaw = 0.0
        self._has_pose = False
        self._mode = "idle"
        self._goal_handle: Any = None
        self._result_future: Any = None
        self._canceled_by_host = False

    def start(self) -> None:
        self._rclpy.init(args=None)
        self._node = self._rclpy.create_node("rosie_agent")
        self._cmd_pub = self._node.create_publisher(
            self._Twist, self.cfg.cmd_vel, 10
        )
        pose_src = self.cfg.pose or self.cfg.odom
        if self.cfg.pose:
            from geometry_msgs.msg import PoseWithCovarianceStamped

            self._PoseCov = PoseWithCovarianceStamped
            self._node.create_subscription(
                self._PoseCov, self.cfg.pose, self._on_pose_msg, 10
            )
        else:
            self._node.create_subscription(
                self._Odometry, self.cfg.odom, self._on_pose_msg, 10
            )
        self._try_start_nav_client()
        self.session.subscribe_json(topics.CMD_VEL, self._on_rosie_cmd_vel)
        self.session.subscribe_json(topics.GOTO, self._on_rosie_goto)
        self.session.subscribe_json(topics.CMD, self._on_rosie_cmd)
        nav_s = (
            f", Rosie goto → {self.cfg.navigate_to_pose} ({self.cfg.frame_id})"
            if self._nav_client is not None
            else ", Rosie goto disabled (nav2_msgs missing)"
        )
        print(
            f"ROS 2 bridge: Rosie cmd_vel → {self.cfg.cmd_vel}, "
            f"{pose_src} → Rosie pose{nav_s}",
            file=sys.stderr,
        )

    def _try_start_nav_client(self) -> None:
        try:
            from nav2_msgs.action import NavigateToPose
            from rclpy.action import ActionClient
        except ImportError as e:
            print(
                f"Nav2 goto disabled (nav2_msgs not importable): {e}",
                file=sys.stderr,
            )
            return
        self._NavigateToPose = NavigateToPose
        self._nav_client = ActionClient(
            self._node, NavigateToPose, self.cfg.navigate_to_pose
        )

    def _on_rosie_cmd_vel(self, msg: dict) -> None:
        handle = None
        was_nav = False
        with self._lock:
            was_nav = self._navigating
            if was_nav:
                handle = self._goal_handle
                self._canceled_by_host = True
        if was_nav:
            self._end_nav("canceled", mode="manual")
            self._cancel_handle(handle)
        else:
            with self._lock:
                self._mode = "manual"
        if self._cmd_pub is None:
            return
        t = self._Twist()
        t.linear.x = float(msg.get("v", 0.0))
        t.angular.z = float(msg.get("w", 0.0))
        self._cmd_pub.publish(t)

    def _on_rosie_cmd(self, msg: dict) -> None:
        if str(msg.get("op", "")) != "stop":
            return
        handle = None
        was_nav = False
        with self._lock:
            was_nav = self._navigating
            if was_nav:
                handle = self._goal_handle
                self._canceled_by_host = True
        if was_nav:
            self._end_nav("canceled", mode="idle")
            self._cancel_handle(handle)
        else:
            with self._lock:
                self._mode = "idle"

    def _on_rosie_goto(self, msg: dict) -> None:
        if "x" not in msg or "y" not in msg:
            return
        x = float(msg["x"])
        y = float(msg["y"])
        incoming = msg.get("goal_id")
        incoming_id = int(incoming) if incoming is not None else None
        handle = None
        was_nav = False
        with self._lock:
            if incoming_id is None:
                incoming_id = self._next_goal_id
                self._next_goal_id += 1
            else:
                self._next_goal_id = max(self._next_goal_id, incoming_id + 1)
            decision = arbitrate_goto(
                self._navigating, self._active_goal_id, incoming_id
            )
            if decision != ACCEPT:
                return
            was_nav = self._navigating
            if was_nav:
                handle = self._goal_handle
                self._canceled_by_host = True
        if was_nav:
            self._end_nav("canceled")
            self._cancel_handle(handle)
        assert incoming_id is not None
        self._start_goal(x, y, incoming_id)

    def _start_goal(self, x: float, y: float, goal_id: int) -> None:
        with self._lock:
            self._navigating = True
            self._active_goal_id = goal_id
            self._target_x = x
            self._target_y = y
            self._mode = "auto"
            self._canceled_by_host = False
            self._goal_handle = None
            self._result_future = None
            yaw = self._pose_yaw if self._has_pose else 0.0
        if self._nav_client is None or self._NavigateToPose is None:
            print(
                "goto aborted: nav2_msgs / ActionClient unavailable",
                file=sys.stderr,
            )
            self._end_nav("aborted")
            return
        if not self._nav_client.server_is_ready():
            if not self._nav_client.wait_for_server(timeout_sec=_NAV_SERVER_WAIT_S):
                print(
                    "goto aborted: NavigateToPose action server not available",
                    file=sys.stderr,
                )
                self._end_nav("aborted")
                return
        goal_msg = self._NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = self.cfg.frame_id
        if self._node is not None:
            goal_msg.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        send_future = self._nav_client.send_goal_async(goal_msg)
        send_future.add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future: Any) -> None:
        try:
            handle = future.result()
        except Exception as e:
            print(f"goto aborted: send_goal failed: {e}", file=sys.stderr)
            self._end_nav("aborted")
            return
        if handle is None or not handle.accepted:
            self._end_nav("aborted")
            return
        with self._lock:
            if not self._navigating:
                self._cancel_handle(handle)
                return
            self._goal_handle = handle
            result_future = handle.get_result_async()
            self._result_future = result_future
        result_future.add_done_callback(self._on_goal_result)

    def _on_goal_result(self, future: Any) -> None:
        with self._lock:
            if future is not self._result_future or not self._navigating:
                return
            canceled = self._canceled_by_host
        try:
            result = future.result()
            status_code = getattr(result, "status", STATUS_ABORTED)
        except Exception as e:
            print(f"goto aborted: result failed: {e}", file=sys.stderr)
            self._end_nav("aborted")
            return
        self._end_nav(rosie_nav_status(status_code, canceled_by_host=canceled))

    def _end_nav(self, status: str, *, mode: str = "idle") -> None:
        with self._lock:
            if not self._navigating:
                return
            goal_id = self._active_goal_id
            x, y = self._pose_x, self._pose_y
            has_pose = self._has_pose
            self._navigating = False
            self._goal_handle = None
            self._result_future = None
            self._canceled_by_host = False
            self._mode = mode
        payload: dict[str, Any] = {
            "goal_id": goal_id,
            "status": status,
        }
        if has_pose:
            payload["x"] = x
            payload["y"] = y
        self.session.publish(
            topics.NAV_RESULT, encode_json(payload), qos=Qos.COMMAND
        )

    def _cancel_handle(self, handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.cancel_goal_async()
        except Exception:
            pass

    def _on_pose_msg(self, msg: Any) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = yaw_from_quat(q.x, q.y, q.z, q.w)
        x, y = float(p.x), float(p.y)
        with self._lock:
            self._pose_x = x
            self._pose_y = y
            self._pose_yaw = yaw
            self._has_pose = True
            navigating = self._navigating
            target_x, target_y = self._target_x, self._target_y
            goal_id = self._active_goal_id
            mode = "auto" if navigating else self._mode
        dist = 0.0
        if navigating:
            dist = math.hypot(target_x - x, target_y - y)
        payload: dict[str, Any] = {
            "x": x,
            "y": y,
            "theta": yaw,
            "heading_deg": yaw * 180.0 / math.pi,
            "mode": mode,
            "navigating": navigating,
            "dist": dist,
        }
        if navigating:
            payload["goal_id"] = goal_id
        self.session.publish(topics.POSE, encode_json(payload))

    def spin_once(self, timeout_sec: float = 0.05) -> None:
        self._rclpy.spin_once(self._node, timeout_sec=timeout_sec)

    def shutdown(self) -> None:
        handle = None
        was_nav = False
        with self._lock:
            was_nav = self._navigating
            if was_nav:
                handle = self._goal_handle
        if was_nav:
            self._end_nav("canceled")
            self._cancel_handle(handle)
        try:
            if self._node is not None:
                self._node.destroy_node()
        except Exception:
            pass
        try:
            if self._rclpy.ok():
                self._rclpy.shutdown()
        except Exception:
            pass
