# Python API

The same things the [laptop tools](laptop-tools.md) do, from a script. Install Rosie on the laptop as in [Getting started](getting-started.md); ROS is not needed.

Every class takes `fleet`, `connect`, and `secure` the same way. `connect` falls back to `ROSIE_CONNECT`, then to the router on this laptop (`tcp/127.0.0.1:7447`). `MobileRobot` and `Session` also read `ROSIE_FLEET` and `ROSIE_ROBOT` when you leave those out; `Fleet` needs the fleet name. Pass `secure=True` when the fleet is in [secure mode](fleet.md#security). Each class is a context manager, so `with` closes its connection.

## MobileRobot

`MobileRobot` drives one robot. It reads the robot's profile, follows its pose topic, and publishes velocity on its command topic.

```python
from rosie import MobileRobot

with MobileRobot("bot1", fleet="lab", profile="rosmaster_x3", secure=True) as bot:
    print(bot.wait_for_pose(3.0))   # {"x": ..., "y": ..., "theta": ..., "heading_deg": ...}
    bot.drive(0.5)                  # 0.5 m forward, using pose feedback
    bot.turn(90)                    # 90 degrees left
    bot.drive_to(1.0, 2.0)          # Nav2 goal; blocks until it finishes
    bot.stop()
```

| Method | What it does |
|---|---|
| `pose()` | Latest pose as `x`, `y` (meters), `theta` (radians), `heading_deg`. Empty dict until the first sample |
| `wait_for_pose(timeout_s=3.0)` | Wait for the first pose; returns `None` on timeout |
| `drive(meters, speed=0.25)` | Drive a signed distance, measured from the pose topic. Negative reverses |
| `turn(degrees, rate_dps=60)` | Turn in place by a signed angle. Positive is left |
| `goto(x, y, yaw=0.0)` | Send a Nav2 `NavigateToPose` goal and return right away |
| `drive_to(x, y, timeout_s=120)` | Send a goal and wait for the result. Raises if navigation fails |
| `drive_route([(x, y), ...])` | `drive_to` each point in order. Not a path planner |
| `stop()` | Zero velocity, and cancel the current goal |
| `teleop()` | WASD keyboard teleop in this terminal |
| `snap()` | Save one camera frame to `./captures/`, open it, and return the file path |
| `camera_live()` | Live camera window (needs `opencv-python`) |

`drive` and `turn` raise `TimeoutError` if no pose arrives, or if the robot does not get there in time. Ctrl-C during any of the blocking calls sends `stop()`.

`goto`, `drive_to`, and `drive_route` need a profile with `nav` set and Nav2 running on the robot. `snap` and `camera_live` need a profile with `camera` set.

Pose is whatever topic the profile names; Odometry and `PoseWithCovarianceStamped` both work. To use a different topic without writing a profile, pass `profile_overrides`:

```python
bot = MobileRobot("bot1", fleet="lab", profile="rosmaster_x3", profile_overrides={
    "pose": {"topic": "/amcl_pose", "type": "geometry_msgs/msg/PoseWithCovarianceStamped"},
})
```

Velocity commands carry a one-second expiry, so the robot's watchdog stops it if your script hangs. When the profile sets `cmd_vel_gate`, commands go to `{topic}_teleop` and the watchdog forwards them. See [Safety](robots/safety.md).

## Fleet

`Fleet` is the view of the whole fleet: who is present, bring-up, and estop.

```python
from rosie import Fleet

with Fleet("lab", secure=True) as fleet:
    fleet.wait(["bot1", "bot2"], timeout_s=30)
    for robot in fleet.robots():
        print(robot.robot_id, robot.status, robot.profile, robot.estop)
    fleet.publish_estop()
```

| Method | What it does |
|---|---|
| `robots()` | Robots whose presence heartbeat is fresh, as `RobotPresence` (`robot_id`, `status`, `profile`, `estop`) |
| `wait(ids, timeout_s=30)` | Block until every id is present. Raises `TimeoutError` naming the missing ones |
| `topics()` | Keys heard under the fleet, grouped by robot |
| `publish_estop()` | Stop every robot. The watchdog latches it; see [Safety](robots/safety.md) |
| `claim_leader(robot_id)` / `get_leader()` | A simple leader claim on `{fleet}/_fleet/coord/leader` |

In secure mode, `robots()` lists only the robots enrolled with `rosie fleet add`. The fleet secret is read from `~/.rosie`. Open mode never reads that file, so a leftover secret does not lock you out of a router on localhost.

## Session

`Session` is the low-level Zenoh connection that `MobileRobot` is built on. Use it to publish or subscribe to a ROS type the profile does not cover, or your own keys.

```python
from rosie import Session

with Session(robot="bot1", fleet="lab", name="script") as session:
    session.subscribe_ros("scan", "sensor_msgs/msg/LaserScan", print, distro="humble")
    session.publish_ros(
        "cmd_vel",
        "geometry_msgs/msg/Twist",
        {"linear": {"x": 0.1}, "angular": {"z": 0.0}},
        distro="humble",
        envelope=True,
        ttl_s=1.0,
    )
    session.spin()
```

Relative keys get the robot's prefix: `scan` becomes `lab/bot1/scan`, which is where the bridge puts the robot's `/scan`. A key with a leading slash is used as is. The topic must be on the robot's bridge allow list, which comes from its profile.

`publish_ros` encodes CDR; `subscribe_ros` decodes it and passes a plain dict. Set `distro` to the robot's ROS distro (default `jazzy`). `envelope=True` attaches an id, an expiry, and a priority beside the message; see [Conventions](conventions.md#command-envelope).

`publish` and `subscribe_json` carry JSON on your own keys, which is handy for messages between your scripts. `examples/minimal-pub-sub` shows that. JSON does not reach ROS on the robot; anything a ROS node should see must be `publish_ros`.

`query` sends a Zenoh query and returns the reply payloads, using the key as given. The Nav2 action client in `rosie.ros.action` builds on it.
