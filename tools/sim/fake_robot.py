"""Scripted ROS 2 robot for the Docker harness. Not imported on the laptop.

Publishes Twist-free pose and a camera frame, and answers NavigateToPose
with an immediate success. DDS stays in this container; the bridge container
is what the laptop talks to.
"""

from __future__ import annotations

import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.action import ActionServer
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from unique_identifier_msgs.msg import UUID

try:
    from nav2_msgs.action import NavigateToPose
except ImportError:  # the image may need ros-<distro>-nav2-msgs
    NavigateToPose = None


class FakeRobot(Node):
    def __init__(self) -> None:
        super().__init__("rosie_fake_robot")
        self._odom = self.create_publisher(Odometry, "/odom", 10)
        self._pose = self.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", 10)
        self._image = self.create_publisher(CompressedImage, "/camera/image_raw/compressed", 10)
        self.create_timer(0.2, self._tick)
        if NavigateToPose is not None:
            self._action = ActionServer(
                self,
                NavigateToPose,
                "/navigate_to_pose",
                self._on_goal,
            )
        self.get_logger().info("fake robot publishing /odom")

    def _tick(self) -> None:
        now = self.get_clock().now().to_msg()
        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = 1.0
        odom.pose.pose.position.y = 2.0
        odom.pose.pose.orientation.w = 1.0
        self._odom.publish(odom)

        pose = PoseWithCovarianceStamped()
        pose.header.stamp = now
        pose.header.frame_id = "map"
        pose.pose.pose = odom.pose.pose
        self._pose.publish(pose)

        image = CompressedImage()
        image.header.stamp = now
        image.format = "jpeg"
        image.data = bytes([0xFF, 0xD8, 0xFF])
        self._image.publish(image)

    def _on_goal(self, goal):
        goal.succeed()
        result = NavigateToPose.Result()
        return result


def main() -> None:
    rclpy.init()
    node = FakeRobot()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
