"""ROS 2 node: estop, teleop deadman, link-loss, and fleet presence.

Run on the robot, in a venv that can import rclpy
(``python3 -m venv --system-site-packages``). The laptop install does not
need ROS.
"""

from __future__ import annotations

import argparse
import threading
import time

from rosie.profiles import load_profile
from rosie.ros.keys import qualify_topic
from rosie.session import Session
from rosie.watchdog.policy import WatchdogPolicy

_RCLPY_HINT = (
    "rosie watchdog runs on the robot and needs rclpy.\n"
    "  python3 -m venv --system-site-packages ~/rosie-venv\n"
    "  source ~/rosie-venv/bin/activate && pip install 'rosie-framework[robot]'\n"
    "  source /opt/ros/$ROS_DISTRO/setup.bash"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosie-watchdog")
    parser.add_argument("--fleet", required=True)
    parser.add_argument("--robot", required=True)
    parser.add_argument("--profile", default="default_ros2")
    parser.add_argument("--connect", default=None)
    parser.add_argument("--secure", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import rclpy
        from rclpy.node import Node
    except ImportError as exc:
        raise SystemExit(_RCLPY_HINT) from exc

    profile = load_profile(args.profile)
    policy = WatchdogPolicy(
        link_loss=profile.link_loss,
        link_loss_s=profile.link_loss_s,
        gate=profile.cmd_vel_gate,
    )
    topic = profile.cmd_vel.topic
    if profile.cmd_vel_gate:
        topic = topic.rstrip("/") + "_teleop"
    relative = qualify_topic(profile.ros_namespace, topic).lstrip("/")

    session = Session(
        robot=args.robot,
        fleet=args.fleet,
        connect=args.connect,
        name="watchdog",
        secure=args.secure,
    )
    try:
        token_key = f"{args.fleet}/{args.robot}/_rosie/watchdog"
        session.session.liveliness().declare_token(token_key)
    except Exception:
        pass

    rclpy.init()
    node = Node("rosie_watchdog")
    ros_type = _import_twist(profile.cmd_vel.type)
    pub = node.create_publisher(ros_type, profile.cmd_vel.topic, 10)
    nav = _nav_client(node, profile.nav_action)

    def _on_cmd(msg: dict) -> None:
        linear = msg.get("linear") or msg.get("twist", {}).get("linear", {})
        angular = msg.get("angular") or msg.get("twist", {}).get("angular", {})
        policy.on_twist(float(linear.get("x") or 0.0), float(angular.get("z") or 0.0), time.time())

    def _on_estop(msg: dict) -> None:
        if str(msg.get("op", "")) == "estop":
            policy.on_estop()
            _cancel(nav)

    def _on_router(_msg: dict) -> None:
        policy.on_router(time.time())

    session.subscribe_ros(relative, profile.cmd_vel.type, _on_cmd, distro=profile.distro)
    session.create_fleet_subscription("estop", _on_estop)
    session.create_fleet_subscription("router", _on_router)

    stop = threading.Event()

    def _beat() -> None:
        while not stop.is_set():
            now = time.time()
            v, w, reason = policy.tick(now)
            if v is not None:
                _publish(pub, ros_type, profile.cmd_vel.type, v, w)
                if reason in ("estop", "link_loss"):
                    _cancel(nav)
            status = "estop" if policy.estop else "ready"
            session.publish(
                "presence",
                {
                    "robot_id": args.robot,
                    "fleet_id": args.fleet,
                    "status": status,
                    "profile": profile.name,
                    "estop": policy.estop,
                },
            )
            stop.wait(0.2 if profile.cmd_vel_gate else 1.0)

    threading.Thread(target=_beat, name="rosie-watchdog", daemon=True).start()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        session.close()
    return 0


def _import_twist(type_name: str):
    if type_name == "geometry_msgs/msg/TwistStamped":
        from geometry_msgs.msg import TwistStamped

        return TwistStamped
    from geometry_msgs.msg import Twist

    return Twist


def _publish(pub, ros_cls, type_name: str, v: float, w: float) -> None:
    msg = ros_cls()
    if type_name.endswith("TwistStamped"):
        msg.twist.linear.x = float(v)
        msg.twist.angular.z = float(w)
    else:
        msg.linear.x = float(v)
        msg.angular.z = float(w)
    pub.publish(msg)


def _nav_client(node, action: str | None):
    if not action:
        return None
    try:
        from nav2_msgs.action import NavigateToPose
        from rclpy.action import ActionClient
    except ImportError:
        return None
    return ActionClient(node, NavigateToPose, action)


def _cancel(client) -> None:
    if client is None:
        return
    try:
        if client.server_is_ready():
            client.cancel_all_goals_async() if hasattr(client, "cancel_all_goals_async") else None
    except Exception:
        pass

