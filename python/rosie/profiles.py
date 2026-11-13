"""Robot profiles: which ROS topics stand in for the fleet contract.

One file is read by the laptop (to encode and decode) and by
``rosie robot setup`` (to write the bridge config).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .ros.keys import fleet_namespace, qualify_topic, topic_key

PROFILES = (
    "default_ros2",
    "turtlebot3",
    "turtlebot4",
    "rosmaster_x3",
    "rosmaster_m3_pro",
)


def profiles_dir() -> Path:
    return Path(__file__).resolve().parent / "profiles"


@dataclass(frozen=True)
class TopicBinding:
    topic: str
    type: str
    type_hash: str | None = None


@dataclass(frozen=True)
class RobotProfile:
    name: str
    distro: str = "jazzy"
    transport: str = "bridge"
    ros_namespace: str = ""
    domain_id: int = 0
    cmd_vel: TopicBinding = field(
        default_factory=lambda: TopicBinding("/cmd_vel", "geometry_msgs/msg/Twist")
    )
    pose: TopicBinding = field(
        default_factory=lambda: TopicBinding("/odom", "nav_msgs/msg/Odometry")
    )
    nav_action: str | None = "/navigate_to_pose"
    nav_type: str = "nav2_msgs/action/NavigateToPose"
    frame_id: str = "map"
    camera: TopicBinding | None = None
    link_loss: str = "stop_after"
    link_loss_s: float = 2.0
    cmd_vel_gate: bool = False
    bridge_allow: dict[str, list[str]] = field(default_factory=dict)
    bridge_rates: list[str] = field(default_factory=list)

    def namespace_for(self, fleet: str, robot: str) -> str:
        if self.transport == "bridge":
            return fleet_namespace(fleet, robot)
        return qualify_topic(f"/{fleet}/{robot}", self.ros_namespace or "/")

    def key_for(self, fleet: str, robot: str, binding: TopicBinding) -> str:
        return topic_key(
            transport=self.transport,
            fleet=fleet,
            robot=robot,
            topic=binding.topic,
            ros_type=binding.type,
            ros_namespace=self.ros_namespace,
            distro=self.distro,
            domain_id=self.domain_id,
            type_hash=binding.type_hash,
        )

    def type_map(self, fleet: str, robot: str) -> dict[str, str]:
        """Zenoh key to ROS type, for bags and ``topic echo``."""
        out = {
            self.key_for(fleet, robot, self.cmd_vel): self.cmd_vel.type,
            self.key_for(fleet, robot, self.pose): self.pose.type,
        }
        if self.camera is not None:
            out[self.key_for(fleet, robot, self.camera)] = self.camera.type
        return out


def load_profile(name: str, overrides: dict[str, Any] | None = None) -> RobotProfile:
    text = str(name).strip()
    path = profiles_dir() / f"{text}.yaml"
    if not path.is_file():
        known = ", ".join(PROFILES)
        raise ValueError(f"unknown robot profile {text!r} (expected one of: {known})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"profile {text!r}: expected a mapping")
    if overrides:
        data = _deep_merge(data, overrides)
    return _from_dict(text, data)


def _from_dict(name: str, data: dict[str, Any]) -> RobotProfile:
    nav = data.get("nav") or {}
    camera = data.get("camera")
    bridge = data.get("bridge") or {}
    allow = bridge.get("allow") or {}
    return RobotProfile(
        name=name,
        distro=str(data.get("distro") or "jazzy").lower(),
        transport=str(data.get("transport") or "bridge"),
        ros_namespace=str(data.get("ros_namespace") or ""),
        domain_id=int(data.get("domain_id") or 0),
        cmd_vel=_binding(data.get("cmd_vel"), "/cmd_vel", "geometry_msgs/msg/Twist"),
        pose=_binding(data.get("pose"), "/odom", "nav_msgs/msg/Odometry"),
        nav_action=_optional(nav.get("action"), "/navigate_to_pose"),
        nav_type=str(nav.get("type") or "nav2_msgs/action/NavigateToPose"),
        frame_id=str(nav.get("frame_id") or data.get("frame_id") or "map"),
        camera=(
            _binding(camera, "/camera/image_raw/compressed", "sensor_msgs/msg/CompressedImage")
            if camera
            else None
        ),
        link_loss=str(data.get("link_loss") or "stop_after"),
        link_loss_s=float(data.get("link_loss_s") or 2.0),
        cmd_vel_gate=bool(data.get("cmd_vel_gate", False)),
        bridge_allow={str(k): [str(x) for x in v] for k, v in allow.items()},
        bridge_rates=[str(x) for x in (bridge.get("rates") or [])],
    )


def _binding(raw: Any, default_topic: str, default_type: str) -> TopicBinding:
    if not isinstance(raw, dict):
        return TopicBinding(default_topic, default_type)
    topic = str(raw.get("topic") or default_topic)
    type_name = str(raw.get("type") or default_type)
    type_hash = raw.get("type_hash")
    return TopicBinding(topic, type_name, str(type_hash) if type_hash else None)


def _optional(value: Any, default: str | None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def with_overrides(profile: RobotProfile, overrides: dict[str, Any] | None) -> RobotProfile:
    if not overrides:
        return profile
    data = {
        "distro": profile.distro,
        "transport": profile.transport,
        "ros_namespace": profile.ros_namespace,
        "cmd_vel": {"topic": profile.cmd_vel.topic, "type": profile.cmd_vel.type},
        "pose": {"topic": profile.pose.topic, "type": profile.pose.type},
        "nav": {"action": profile.nav_action, "frame_id": profile.frame_id},
    }
    return _from_dict(profile.name, _deep_merge(data, overrides))


def bridge_config(
    profile: RobotProfile,
    *,
    fleet: str,
    robot: str,
    connect: str,
    mode: str = "client",
) -> dict[str, Any]:
    """JSON-compatible config for ``zenoh-bridge-ros2dds -c``."""
    namespace = fleet_namespace(fleet, robot) if profile.transport == "bridge" else "/"
    ros2dds: dict[str, Any] = {
        "namespace": namespace,
        "nodename": f"rosie_{robot}",
    }
    if profile.bridge_allow:
        ros2dds["allow"] = profile.bridge_allow
    if profile.bridge_rates:
        ros2dds["pub_max_frequencies"] = list(profile.bridge_rates)
    zenoh: dict[str, Any] = {"mode": mode}
    if mode == "client":
        zenoh["connect"] = {"endpoints": [connect]}
    elif mode == "peer":
        zenoh["connect"] = {"endpoints": [connect]}
        zenoh["listen"] = {"endpoints": ["tcp/0.0.0.0:7447"]}
    else:
        zenoh["listen"] = {"endpoints": ["tcp/0.0.0.0:7447"]}
        if connect:
            zenoh["connect"] = {"endpoints": [connect]}
    return {"plugins": {"ros2dds": ros2dds}, **zenoh}
