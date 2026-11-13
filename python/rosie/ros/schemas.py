"""ros2msg schema text for MCAP export. Enough for Foxglove to decode CDR."""

from __future__ import annotations

_VECTOR3 = """\
float64 x
float64 y
float64 z
"""

_SCHEMAS: dict[str, str] = {
    "geometry_msgs/msg/Vector3": _VECTOR3,
    "geometry_msgs/msg/Point": _VECTOR3,
    "geometry_msgs/msg/Quaternion": """\
float64 x
float64 y
float64 z
float64 w
""",
    "builtin_interfaces/msg/Time": """\
int32 sec
uint32 nanosec
""",
    "std_msgs/msg/Header": """\
builtin_interfaces/Time stamp
string frame_id
""",
    "geometry_msgs/msg/Twist": """\
geometry_msgs/Vector3 linear
geometry_msgs/Vector3 angular
""",
    "geometry_msgs/msg/TwistStamped": """\
std_msgs/Header header
geometry_msgs/Twist twist
""",
    "geometry_msgs/msg/Pose": """\
geometry_msgs/Point position
geometry_msgs/Quaternion orientation
""",
    "geometry_msgs/msg/PoseWithCovariance": """\
geometry_msgs/Pose pose
float64[36] covariance
""",
    "geometry_msgs/msg/PoseWithCovarianceStamped": """\
std_msgs/Header header
geometry_msgs/PoseWithCovariance pose
""",
    "geometry_msgs/msg/TwistWithCovariance": """\
geometry_msgs/Twist twist
float64[36] covariance
""",
    "nav_msgs/msg/Odometry": """\
std_msgs/Header header
string child_frame_id
geometry_msgs/PoseWithCovariance pose
geometry_msgs/TwistWithCovariance twist
""",
    "sensor_msgs/msg/CompressedImage": """\
std_msgs/Header header
string format
uint8[] data
""",
}


def schema_text(type_name: str) -> str:
    """Concatenated ros2msg definition, dependencies first-seen order."""
    seen: list[str] = []

    def walk(name: str) -> None:
        ros_name = name if "/msg/" in name else _expand(name)
        if ros_name in seen:
            return
        if ros_name not in _SCHEMAS:
            return
        seen.append(ros_name)
        for line in _SCHEMAS[ros_name].splitlines():
            parts = line.split()
            if len(parts) == 2 and "/" in parts[0] and not parts[0].startswith("uint"):
                walk(parts[0])

    walk(type_name)
    if not seen:
        return f"string note\n"
    chunks = [_SCHEMAS[seen[0]].rstrip() + "\n"]
    for name in seen[1:]:
        short = name.replace("/msg/", "/")
        chunks.append(f"================================================================================\nMSG: {short}\n{_SCHEMAS[name]}")
    return "".join(chunks)


def schema_bytes(type_name: str) -> bytes:
    return schema_text(type_name).encode("utf-8")


def _expand(short: str) -> str:
    if "/msg/" in short:
        return short
    package, _, rest = short.partition("/")
    return f"{package}/msg/{rest}"
