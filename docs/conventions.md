# Conventions

Shared contracts for Rosie. Robots choose a **robot id** (and optional **fleet**)
and join a shared network (dedicated AP for fleets; SoftAP only for solo
fallback); they should follow these topic names and units so laptop tools and
other robots interoperate.

See also [Messages](messages.md) and [Bring Your Own Robot](robots/byor.md).

## Identity

| Entity | Role |
|--------|------|
| **Robot** | Required id; topic boundary for that machine |
| **Fleet** | Optional shared scope for multi-robot work |
| **Session** | Process-local Zenoh handle bound to a robot (+ fleet) |
| **Topic** | Actual I/O (`pose`, `cmd_vel`, …)—not one Session per sensor |

## Topic naming

Zenoh key expressions are `/`-joined paths (no leading slash on the wire):

| Scope | Pattern | Example |
|-------|---------|---------|
| Solo robot | `{robot}/{name}` | `car1/cmd_vel` |
| Robot in a fleet | `{fleet}/{robot}/{name}` | `lab/car1/pose` |
| Fleet-wide | `{fleet}/_fleet/{name}` | `lab/_fleet/estop` |
| Absolute / global | strip leading `/` | `/global/estop` → `global/estop` |

The segment `_fleet` is **reserved** — do not use it as a robot id.

### Resolution

`Session(robot=..., fleet=...)` prefixes **relative** names. A leading `/` marks
an **absolute** name. Fleet-scoped helpers use `{fleet}/_fleet/...`.

| Input | `robot="car1"` | `robot="car1", fleet="lab"` |
|-------|----------------|------------------------------|
| `"cmd_vel"` | `car1/cmd_vel` | `lab/car1/cmd_vel` |
| `topics.POSE` | `car1/pose` | `lab/car1/pose` |
| `"/global/estop"` | `global/estop` | `global/estop` |
| `resolve_fleet_name("estop")` | (error: no fleet) | `lab/_fleet/estop` |

```python
from rosie import Session, topics

session = Session(robot="car1", name="teleop")
session.publish_msg(topics.CMD_VEL, ...)   # → car1/cmd_vel
session.publish("/global/estop", {...})    # → global/estop
```

Firmware uses the same rules on `rosie::Session(ROBOT_ID, FLEET_ID)`.

### Standard relative names

Constants in `rosie.topics`:

| Constant | Relative name | Typical direction | Payload |
|----------|---------------|-------------------|---------|
| `POSE` | `pose` | robot → host | JSON `Pose2D` (+ MobileBase extras below) |
| `LOG` | `log` | robot → host | JSON `Log` |
| `CMD_VEL` | `cmd_vel` | host → robot | JSON `Twist` |
| `GOTO` | `goto` | host → robot | JSON `Goto` (`x`,`y`,`goal_id?`) |
| `NAV_RESULT` | `nav_result` | robot → host | JSON `NavResult` (goto terminal outcome) |
| `CMD` | `cmd` | host → robot | JSON `Cmd` (`stop`, `zero`, `set_gains`, …) |
| `CONTROL` | `control` | robot → host | velocity gains + wheel vel telemetry |
| `PRESENCE` | `presence` | robot → host | JSON `RobotPresence` |
| `CAMERA_COMPRESSED` | `camera/compressed` | robot → host | raw bytes (e.g. JPEG) |

Custom relative names: pass any string (`"sensors/imu"`) or an absolute `"/..."`.

### Fleet robot contract

A robot is a first-class fleet member if it honors this contract — regardless of
whether it runs Rosie **natively** (MCU firmware / Linux `rosie run`) or via
a **bridge** (`rosie agent` in front of ROS 2). Laptop tools (`teleop`,
`viz`, `bag`, `fleet`, `MobileRobot`) judge native and bridged robots the same
way. See [Bridges](robots/bridges.md) for native-vs-bridge guidance and `rosie agent`.

| Level | Topic(s) | Requirement |
|-------|----------|-------------|
| **MUST** | `presence` | Publish ~1 Hz so hosts can discover the robot |
| **MUST** | `pose` | Publish `x`, `y`, `theta` (meters / radians) for viz, follow, logging |
| **MUST** | `cmd_vel` | Accept `Twist` (`v`, `w`) for teleop / manual control |
| **SHOULD** | `goto` + `nav_result` | Accept a planar goal and report a terminal outcome (enables `drive_to` / `rosie drive`) |
| **MAY** | `camera/compressed` | Publish JPEG bytes for the viz camera panel |
| **MAY** | `log`, `cmd`, `control` | Structured logs, custom ops, velocity-gain telemetry |

All keys resolve under `{fleet}/{robot}/…`. Extra JSON fields are allowed as long
as the standard fields remain present. A bridge simply maps these to/from the
robot's own topics (e.g. ROS `/cmd_vel`, `/odom`).

### Environment variables

| Variable | Meaning |
|----------|---------|
| `ROSIE_CONNECT` | Host Zenoh endpoint (default `tcp/127.0.0.1:7447`). Override for a remote router. |
| `ROSIE_ROBOT` | Default Session robot id |
| `ROSIE_FLEET` | Default Session fleet id (optional) |
| `ROSIE_PARAM_<NAME>` | Override a local parameter (`declare_parameter`) |
| `ROSIE_FIRMWARE` | Override path to the PlatformIO firmware library |
| `ROSIE_HOME` | Cache root (default `~/.rosie`) for zenohd / pio_libs |

## Units and frames

| Quantity | Unit / convention |
|----------|-------------------|
| Linear speed `v` | m/s; + forward, − reverse |
| Yaw rate `w` | rad/s; + left / CCW, − right / CW |
| Position `x`, `y` | meters |
| Yaw `theta` | radians; convention is robot-defined (often +CCW from +x) |

There is **no TF tree** and **no `frame_id`**. Pose and goto share whatever frame
the robot defines (document it in the robot README). Host helpers above `goto`
are documented in [Mobile base → Navigation helpers](robots/mobile-base.md#navigation-helpers).

## Binary vs JSON topics

- Structured messages: UTF-8 JSON with a top-level `stamp` ([architecture](architecture.md)).
- Compressed images and similar: **raw bytes**, not JSON.
- Robots may add **extra JSON fields** on standard topics as long as the std
  fields remain present. **MobileBase** pose extras (progress while navigating):

  | Extra field | Meaning |
  |-------------|---------|
  | `heading_deg` | yaw in degrees (convenience) |
  | `dist` | distance to current goto target (m) |
  | `navigating` | bool — AUTO goto in progress |
  | `goal_id` | active goto attempt id (while `navigating`) |
  | `mode` | `"idle"` / `"manual"` / `"auto"` |
  | `imu_ok` / `imu_heading` | optional IMU status |

  Terminal outcome is **`nav_result`**, not an edge on `navigating`. See
  [Mobile base → Navigation helpers](robots/mobile-base.md#navigation-helpers).

  Robot description for MCU bring-up is **`robot.yaml`** (not URDF) — see
  [Mobile base](robots/mobile-base.md).

## Multi-robot / fleet

- Networking: **dedicated AP** + all robots/hosts as Wi‑Fi stations + one
  `rosie router` — see [Fleet networking](fleet/networking.md). SoftAP is
  solo-robot fallback only.
- Membership: [Fleet management](fleet/management.md)
  (`rosie fleet init` / `add`, `router --fleet`). Open vs secure:
  [Security](fleet/security.md) (`--secure` for usrpwd + allowlist).
- Publish `presence` (~1 Hz) so hosts can discover live robots.
- Host: `rosie fleet list|wait|topics`, `rosie topic list|echo`, `rosie bag …`,
  or `from rosie import Fleet, load_manifest`.
- Fleet-wide signals: `estop`, `coord/leader` under `{fleet}/_fleet/...`.
- Host sessions default to the local router (`tcp/127.0.0.1:7447`). Set
  `ROSIE_CONNECT` only when the router is on another machine. MCU robots use
  `robot.yaml` `network.connect` with the router host’s LAN IP.

## What Rosie intentionally omits

Compared to ROS 2, Rosie does **not** provide:

- QoS profiles (reliability / history / depth)
- TF / `frame_id`
- A remote parameter server (params are local + env override only)
- Services and ROS-style action servers (long-running goals use ordinary
  topics: `goto` + `nav_result` — see [Mobile base](robots/mobile-base.md#navigation-helpers))
- Launch-file topic remapping (use absolute names or change robot/fleet;
  team bring-up is `rosie fleet wait` / a fleet manifest + presence wait, not
  N remapped launches)
- A full RViz-class visualizer (use lightweight `rosie viz` for 2D fleet poses)

Prefer `std_msgs` for cross-robot contracts; use plain JSON or custom keys when a
robot needs something outside that set.

Full comparison: [Motivation](motivation.md).
