"""ROS 2 ↔ Rosie bridge backend."""

from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING, Any

from rosie import topics
from rosie.messages import encode_json

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
    """Subscribe Rosie cmd_vel / publish pose; map ROS /cmd_vel and /odom."""

    def __init__(self, session: Session, cfg: AgentConfig) -> None:
        self.session = session
        self.cfg = cfg
        self._rclpy = require_rclpy()
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry

        self._Twist = Twist
        self._Odometry = Odometry
        self._node: Any = None
        self._cmd_pub: Any = None

    def start(self) -> None:
        self._rclpy.init(args=None)
        self._node = self._rclpy.create_node("rosie_agent")
        self._cmd_pub = self._node.create_publisher(
            self._Twist, self.cfg.cmd_vel, 10
        )
        self._node.create_subscription(
            self._Odometry, self.cfg.odom, self._on_odom, 10
        )
        self.session.subscribe_json(topics.CMD_VEL, self._on_rosie_cmd_vel)
        print(
            f"ROS 2 bridge: Rosie cmd_vel → {self.cfg.cmd_vel}, "
            f"{self.cfg.odom} → Rosie pose",
            file=sys.stderr,
        )

    def _on_rosie_cmd_vel(self, msg: dict) -> None:
        if self._cmd_pub is None:
            return
        t = self._Twist()
        t.linear.x = float(msg.get("v", 0.0))
        t.angular.z = float(msg.get("w", 0.0))
        self._cmd_pub.publish(t)

    def _on_odom(self, msg: Any) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = yaw_from_quat(q.x, q.y, q.z, q.w)
        self.session.publish(
            topics.POSE,
            encode_json(
                {
                    "x": float(p.x),
                    "y": float(p.y),
                    "theta": float(yaw),
                    "heading_deg": float(yaw) * 180.0 / math.pi,
                    "mode": "auto",
                }
            ),
        )

    def spin_once(self, timeout_sec: float = 0.05) -> None:
        self._rclpy.spin_once(self._node, timeout_sec=timeout_sec)

    def shutdown(self) -> None:
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
