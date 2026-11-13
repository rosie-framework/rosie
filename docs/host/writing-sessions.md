# Writing sessions

`Session` is the laptop's Zenoh connection for one robot. Most users want [MobileRobot](mobile-robot.md) instead. Use a session when you are publishing your own keys or a ROS type the profile does not wrap.

```python
from rosie import Session

with Session(robot="bot1", fleet="lab", name="notes") as session:
    session.publish("notes", {"text": "hello"})
    session.subscribe_json("notes", print)
    session.spin()
```

Relative keys become `lab/bot1/notes`. A leading slash is an absolute key and is not prefixed.

ROS types:

```python
session.publish_ros(
    "cmd_vel",
    "geometry_msgs/msg/Twist",
    {"linear": {"x": 0.1}, "angular": {"z": 0.0}},
    envelope=True,
    ttl_s=1.0,
)
session.subscribe_ros("odom", "nav_msgs/msg/Odometry", print)
```

`publish_ros` encodes CDR. `envelope=True` attaches `id`, `expiry`, and `priority` next to the payload. See [Conventions](../conventions.md). `subscribe_ros` passes a plain dict to the callback.

`query` sends a Zenoh query and returns reply payloads. The key is used as given. Action clients in `rosie.ros.action` build the bridge key themselves (`lab/bot1/navigate_to_pose/_action/send_goal`).

`mode="peer"` or `mode="router"` listens on `tcp/0.0.0.0:7447` as well as connecting. The default `client` only connects, to `tcp/127.0.0.1:7447` unless you pass `connect` or set `ROSIE_CONNECT`.

The example in `examples/minimal-pub-sub` is this JSON path. It is not how velocity is sent. Velocity is `publish_ros` or `MobileRobot`.
