# Writing sessions (Python)

A **Session** is a process-local Zenoh handle bound to a **robot** and
**fleet**. Sensors and commands are **topics** under that robot—not separate
sessions per driver. Host tools each open their **own** Session (often with the
same robot id) to publish into / subscribe from that namespace — see
[Architecture → Bus, Session, Topic](../architecture.md#bus-session-topic).

For MobileBase robots, prefer the higher-level **[`MobileRobot`](mobile-robot.md)**
helper or the [`rosie drive`](mobile-robot.md#rosie-drive) CLI.
Onboard paths: `cmd_vel` (MANUAL) or `goto` → `pose` → `nav_result` (AUTO) —
[Motion on the robot](../robots/mobile-base.md#motion-on-the-robot).
`drive_to` waits on `nav_result`. Raw `Session` remains the right tool for
custom hosts and non-mobile robots.

```python
from rosie import MobileRobot

with MobileRobot(robot="car1", fleet="lab") as bot:  # or config_path="robot.yaml"
    bot.wait_for_pose()
    bot.drive_to(1.0, 0.0)
```

Full kwargs and methods: [MobileRobot](mobile-robot.md).

```python
from rosie import Session, topics
from rosie.std_msgs import Twist

session = Session(robot="demo", fleet="lab", name="teleop")

# Relative names → lab/demo/cmd_vel
session.publish_msg(topics.CMD_VEL, Twist(v=0.2, w=0.0))

# Or publish a plain dict (stamp added if missing)
session.publish(topics.CMD_VEL, {"v": 0.2, "w": 0.0})

def on_pose(msg: dict) -> None:
    print(msg)

session.subscribe_json(topics.POSE, on_pose)
session.spin()  # Ctrl-C to stop
```

Prefer a context manager so the connection closes cleanly:

```python
with Session(robot="demo", fleet="lab", name="listener") as session:
    session.subscribe_json(topics.POSE, print)
    session.spin()
```

```python
session = Session(robot="car1", fleet="lab")
session.resolve_name("pose")          # → lab/car1/pose
session.resolve_fleet_name("estop")   # → lab/_fleet/estop
```

## Robot / fleet and topic names

| Form | Example | Resolved (`robot="demo"`, `fleet="lab"`) |
|------|---------|------------------------------------------|
| Relative | `"cmd_vel"` | `lab/demo/cmd_vel` |
| Absolute | `"/global/estop"` | `global/estop` |
| Fleet-scoped | `publish_fleet("estop")` | `lab/_fleet/estop` |

`session.resolve_name("cmd_vel")` returns the wire key for logging. See [Conventions](../conventions.md).

## Publish helpers

| Method | Use when |
|--------|----------|
| `publish_msg(name, msg, qos=...)` | Typed `std_msgs` objects (`Twist`, `Pose2D`, …) |
| `publish(name, dict, qos=...)` | Plain JSON dicts (stamp injected if missing) |
| `publish(name, bytes, qos=...)` | Raw payloads (JPEG, etc.) |
| `publish_fleet(name, …, qos=...)` | Fleet-wide topics under `{fleet}/_fleet/...` |

Optional `qos=` selects a delivery class (`Qos.STREAM` default, `Qos.COMMAND`
for `cmd` / `goto`, `Qos.CRITICAL` for fleet estop, `Qos.BULK` for camera).
See [Delivery and validity](../conventions.md#delivery-and-validity).

```python
from rosie import Qos, topics

session.publish(topics.CMD, {"op": "stop"}, qos=Qos.COMMAND)
```

## Subscribe helpers

| Method | Payload |
|--------|---------|
| `subscribe_json(name, handler)` | `dict` |
| `subscribe_bytes(name, handler)` | `bytes` |
| `create_subscription(name, callback, msg_type=...)` | typed message when using generated types |
| `create_fleet_subscription(...)` | fleet-scoped topics |

## Parameters

Local only (no remote parameter server):

```python
session.declare_parameter("max_speed", 0.5)
speed = session.get_parameter("max_speed")
# Override via env: ROSIE_PARAM_MAX_SPEED=0.3
```

## Timers

```python
def tick():
    session.publish(topics.CMD_VEL, {"v": 0.0, "w": 0.0})

session.create_timer(0.1, tick)
session.spin()
```

## Topic constants

`rosie.topics` holds relative suffixes: `POSE`, `LOG`, `CMD_VEL`, `GOTO`, `CMD`,
`CAMERA_COMPRESSED`, `PRESENCE`. Full table: [Conventions](../conventions.md).

## Teleop

Reusable WASD → `Twist` on `cmd_vel`:

```python
from rosie import Session
from rosie.tools.teleop_twist import run_teleop

with Session(robot="demo", fleet="lab", name="teleop") as session:
    run_teleop(session, v_fwd=0.25, v_turn=1.2)
```

Or: `rosie teleop --robot demo --fleet lab`. Pass `on_stop=` for robot-specific deadman
(e.g. publish a `Cmd`). Speeds and key maps are caller policy.

## Fleet helper

For multi-robot discovery and coordination on the host, use **`rosie.Fleet`**
(or `rosie fleet list` / `wait` / `estop` / `leader`). Kwargs and methods:
[Fleet](fleet.md). Networking for fleets uses a **dedicated AP** (not SoftAP) —
[Fleet networking](../fleet/networking.md). See also [Conventions](../conventions.md).
