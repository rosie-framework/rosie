"""CDR encode and decode for the ROS messages Rosie sends and receives.

``rosbags`` is pure Python, so the laptop does not need a ROS install.
Nav2 action types are not in the standard stores; they are registered from
the message definitions below (Humble through Lyrical share this shape).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
from rosbags.typesys import Stores, get_types_from_msg, get_typestore

_DISTROS = {
    "humble": Stores.ROS2_HUMBLE,
    "jazzy": Stores.ROS2_JAZZY,
    "lyrical": Stores.ROS2_LYRICAL,
}

# nav2_msgs/action/NavigateToPose, stable across Humble, Jazzy, and Lyrical.
_NAV2_MSGS: dict[str, str] = {
    "nav2_msgs/action/NavigateToPose_Goal": (
        "geometry_msgs/PoseStamped pose\nstring behavior_tree\n"
    ),
    "nav2_msgs/action/NavigateToPose_Result": "std_msgs/Empty result\n",
    "nav2_msgs/action/NavigateToPose_Feedback": (
        "geometry_msgs/PoseStamped current_pose\n"
        "builtin_interfaces/Duration navigation_time\n"
        "builtin_interfaces/Duration estimated_time_remaining\n"
        "int16 number_of_recoveries\n"
        "float32 distance_remaining\n"
    ),
    "nav2_msgs/action/NavigateToPose_SendGoal_Request": (
        "unique_identifier_msgs/UUID goal_id\n"
        "nav2_msgs/action/NavigateToPose_Goal goal\n"
    ),
    "nav2_msgs/action/NavigateToPose_SendGoal_Response": (
        "bool accepted\nbuiltin_interfaces/Time stamp\n"
    ),
    "nav2_msgs/action/NavigateToPose_GetResult_Request": (
        "unique_identifier_msgs/UUID goal_id\n"
    ),
    "nav2_msgs/action/NavigateToPose_GetResult_Response": (
        "int8 status\nnav2_msgs/action/NavigateToPose_Result result\n"
    ),
    "nav2_msgs/action/NavigateToPose_FeedbackMessage": (
        "unique_identifier_msgs/UUID goal_id\n"
        "nav2_msgs/action/NavigateToPose_Feedback feedback\n"
    ),
    "action_msgs/srv/CancelGoal_Request": "action_msgs/GoalInfo goal_info\n",
    "action_msgs/srv/CancelGoal_Response": (
        "int8 return_code\naction_msgs/GoalInfo[] goals_canceling\n"
    ),
}

SEND_GOAL_REQUEST = "nav2_msgs/action/NavigateToPose_SendGoal_Request"
SEND_GOAL_RESPONSE = "nav2_msgs/action/NavigateToPose_SendGoal_Response"
GET_RESULT_REQUEST = "nav2_msgs/action/NavigateToPose_GetResult_Request"
GET_RESULT_RESPONSE = "nav2_msgs/action/NavigateToPose_GetResult_Response"
CANCEL_GOAL_REQUEST = "action_msgs/srv/CancelGoal_Request"
CANCEL_GOAL_RESPONSE = "action_msgs/srv/CancelGoal_Response"
FEEDBACK_MESSAGE = "nav2_msgs/action/NavigateToPose_FeedbackMessage"


def supported_distros() -> tuple[str, ...]:
    return tuple(_DISTROS)


@lru_cache(maxsize=8)
def typestore(distro: str = "jazzy"):
    """Typestore for ``distro``, with Nav2 action types registered."""
    name = str(distro).strip().lower()
    if name not in _DISTROS:
        raise ValueError(
            f"unsupported ROS distro {distro!r} (expected {', '.join(_DISTROS)})"
        )
    store = get_typestore(_DISTROS[name])
    extra: dict = {}
    for type_name, text in _NAV2_MSGS.items():
        extra.update(get_types_from_msg(text, type_name))
    store.register(extra)
    return store


def encode(type_name: str, value: dict[str, Any], *, distro: str = "jazzy") -> bytes:
    """Serialize a plain dict to a CDR buffer, including the 4-byte header."""
    store = typestore(distro)
    message = _build(store, type_name, value or {})
    raw = store.serialize_cdr(message, type_name)
    return bytes(raw)


def decode(type_name: str, payload: bytes, *, distro: str = "jazzy") -> dict[str, Any]:
    """Deserialize a CDR buffer (with header) to a plain dict."""
    store = typestore(distro)
    message = store.deserialize_cdr(payload, type_name)
    data = _to_plain(message)
    if not isinstance(data, dict):
        raise TypeError(f"decoded {type_name} was not a message")
    return data


def _ros_name(annotation: str) -> str | None:
    if "__" not in annotation or annotation.startswith("list") or annotation.startswith("np."):
        return None
    if annotation.startswith("ClassVar"):
        return None
    return annotation.replace("__", "/")


def _build(store: Any, type_name: str, value: Any) -> Any:
    cls = store.types[type_name]
    if not isinstance(value, dict):
        raise TypeError(f"{type_name} expects a dict, got {type(value).__name__}")
    kwargs: dict[str, Any] = {}
    for field, anno in cls.__annotations__.items():
        if field.startswith("_"):
            continue
        if field not in value or value[field] is None:
            kwargs[field] = _missing(store, anno, field)
            continue
        kwargs[field] = _convert_field(store, anno, value[field], field)
    return cls(**kwargs)


def _convert_field(store: Any, anno: str, value: Any, field: str) -> Any:
    nested = _ros_name(anno)
    if nested:
        if isinstance(value, dict):
            return _build(store, nested, value)
        raise TypeError(f"{field} expects a {nested} dict")
    if "ndarray" in anno:
        return _as_array(anno, value, field)
    if anno.startswith("list["):
        if "GoalInfo" in anno:
            items = value or []
            return [_build(store, "action_msgs/msg/GoalInfo", item) for item in items]
        return value
    if "ndarray" in anno:
        return _as_array(anno, value, field)
    if anno == "str":
        return str(value)
    if anno == "bool":
        return bool(value)
    if anno == "int":
        return int(value)
    if anno == "float":
        return float(value)
    return value


def _missing(store: Any, anno: str, field: str) -> Any:
    nested = _ros_name(anno)
    if nested:
        return _build(store, nested, {})
    if "ndarray" in anno:
        return _as_array(anno, b"" if "uint8" in anno else None, field)
    if anno == "str":
        return ""
    if anno == "bool":
        return False
    if anno == "int":
        return 0
    if anno == "float":
        return 0.0
    if anno.startswith("list"):
        return []
    raise TypeError(f"no default for {field} ({anno})")


def _as_array(anno: str, value: Any, field: str) -> Any:
    if "uint8" in anno:
        if value is None or value == b"" or value == []:
            return np.zeros(0, dtype=np.uint8)
        if isinstance(value, (bytes, bytearray)):
            return np.frombuffer(bytes(value), dtype=np.uint8).copy()
        return np.asarray(list(value), dtype=np.uint8)
    length = 36 if "covariance" in field else 0
    if value is None:
        if length == 0:
            return np.zeros(0, dtype=np.float64)
        return np.zeros(length, dtype=np.float64)
    array = np.asarray(list(value), dtype=np.float64)
    return array


def _to_plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype == np.uint8:
            return value.tobytes()
        return [float(x) for x in value.tolist()]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    annotations = getattr(value, "__annotations__", None)
    msgtype = getattr(value, "__msgtype__", None)
    if annotations and msgtype:
        out: dict[str, Any] = {}
        for field in annotations:
            if field.startswith("_"):
                continue
            out[field] = _to_plain(getattr(value, field))
        return out
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value

