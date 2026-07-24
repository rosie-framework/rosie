"""Rosie — lightweight ROS2-inspired framework over Zenoh."""

from .messages import decode_json, encode_json, stamp_now, with_stamp
from .session import Session
from .fleet import Fleet, TopicMap
from .manifest import (
    FleetManifest,
    RobotSpec,
    load_manifest,
    resolve_manifest,
)
from .mobile_robot import MobileRobot
from .robot_config import RobotConfig, load_robot_config
from . import std_msgs
from . import topics

__all__ = [
    "Session",
    "Fleet",
    "TopicMap",
    "FleetManifest",
    "RobotSpec",
    "load_manifest",
    "resolve_manifest",
    "MobileRobot",
    "RobotConfig",
    "load_robot_config",
    "topics",
    "encode_json",
    "decode_json",
    "stamp_now",
    "with_stamp",
    "std_msgs",
]

__version__ = "0.4.0"
