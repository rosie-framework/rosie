"""Map a robot and a ROS name onto a Zenoh key.

Two layouts:

* ``bridge`` — ``zenoh-bridge-ros2dds``. A namespace ``/lab/bot1`` plus topic
  ``/cmd_vel`` becomes ``lab/bot1/cmd_vel``. Leading slashes are stripped;
  inner slashes stay as key separators. Actions live under
  ``<action>/_action/{send_goal,cancel_goal,get_result,feedback,status}``.
* ``rmw_zenoh`` — ``<domain>/<topic>/<dds_type>/<type_hash>``. Humble uses
  ``TypeHashNotSupported``. Jazzy and later use an ``RIHS01_`` hash. There is
  no bridge namespace: put ``{fleet}/{robot}`` in the ROS namespace so the
  topic segments still start with the fleet identity.
"""

from __future__ import annotations

HUMBLE_TYPE_HASH = "TypeHashNotSupported"

_ACTION_SUFFIXES = (
    "send_goal",
    "cancel_goal",
    "get_result",
    "feedback",
    "status",
)


def normalize_ros_name(name: str) -> str:
    """Return a ROS name with a single leading slash."""
    text = str(name).strip()
    if not text:
        raise ValueError("ROS name must be non-empty")
    if not text.startswith("/"):
        text = "/" + text
    while "//" in text:
        text = text.replace("//", "/")
    return text


def qualify_topic(ros_namespace: str, topic: str) -> str:
    """Prefix ``topic`` with the robot's own ROS namespace, if it has one."""
    topic = normalize_ros_name(topic)
    ns = str(ros_namespace or "").strip()
    if not ns or ns == "/":
        return topic
    ns = normalize_ros_name(ns).rstrip("/")
    return f"{ns}{topic}"


def ros_type_to_dds(ros_type: str) -> str:
    """``geometry_msgs/msg/Twist`` to ``geometry_msgs::msg::dds_::Twist_``."""
    text = str(ros_type).strip()
    if not text or "/" not in text:
        raise ValueError(f"not a ROS type name: {ros_type!r}")
    result = text.replace("/", "::")
    head, _, tail = result.rpartition("::")
    return f"{head}::dds_::{tail}_"


def bridge_key(namespace: str, ros_name: str) -> str:
    """Zenoh key the DDS bridge publishes for ``ros_name`` under ``namespace``."""
    ros = normalize_ros_name(ros_name)
    ns = str(namespace or "/").strip() or "/"
    if not ns.startswith("/"):
        ns = "/" + ns
    if ns == "/":
        return ros[1:]
    return f"{ns.strip('/')}/{ros[1:]}"


def fleet_namespace(fleet: str, robot: str) -> str:
    """Bridge namespace that keeps Rosie identity: ``/{fleet}/{robot}``."""
    fleet = str(fleet).strip().strip("/")
    robot = str(robot).strip().strip("/")
    if not fleet or not robot or "/" in fleet or "/" in robot:
        raise ValueError("fleet and robot must be non-empty single path segments")
    return f"/{fleet}/{robot}"


def action_key(namespace: str, action: str, suffix: str) -> str:
    """Zenoh key for one Nav2 action sub-interface."""
    if suffix not in _ACTION_SUFFIXES:
        raise ValueError(
            f"action suffix must be one of {', '.join(_ACTION_SUFFIXES)}"
        )
    base = bridge_key(namespace, action).rstrip("/")
    return f"{base}/_action/{suffix}"


def rmw_key(
    topic: str,
    ros_type: str,
    *,
    domain_id: int = 0,
    distro: str = "jazzy",
    type_hash: str | None = None,
) -> str:
    """Data key expression used by ``rmw_zenoh``."""
    distro = str(distro).strip().lower()
    if distro == "humble":
        hash_part = HUMBLE_TYPE_HASH
    else:
        hash_part = str(type_hash or "").strip()
        if not hash_part:
            raise ValueError(
                f"rmw_zenoh on {distro} needs an RIHS01 type hash for {ros_type}"
            )
        if not hash_part.startswith("RIHS01_") and hash_part != HUMBLE_TYPE_HASH:
            hash_part = "RIHS01_" + hash_part
    relative = normalize_ros_name(topic)[1:]
    return f"{int(domain_id)}/{relative}/{ros_type_to_dds(ros_type)}/{hash_part}"


def topic_key(
    *,
    transport: str,
    fleet: str,
    robot: str,
    topic: str,
    ros_type: str,
    ros_namespace: str = "",
    distro: str = "jazzy",
    domain_id: int = 0,
    type_hash: str | None = None,
) -> str:
    """Key a laptop uses to pub/sub one ROS topic for one fleet robot."""
    qualified = qualify_topic(ros_namespace, topic)
    kind = str(transport or "bridge").strip().lower()
    if kind == "bridge":
        return bridge_key(fleet_namespace(fleet, robot), qualified)
    if kind in ("rmw_zenoh", "rmw"):
        # Identity lives in the ROS namespace, because rmw_zenoh keys have no
        # separate fleet prefix slot.
        named = qualify_topic(f"/{fleet}/{robot}", qualified)
        return rmw_key(
            named,
            ros_type,
            domain_id=domain_id,
            distro=distro,
            type_hash=type_hash,
        )
    raise ValueError(f"unknown transport {transport!r} (bridge or rmw_zenoh)")
