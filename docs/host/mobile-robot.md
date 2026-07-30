# MobileRobot (Python)

Host-side helper for robots that speak the **MobileBase** topic contract
(`cmd_vel`, `goto` / `nav_result`, `pose`, `cmd`, …). Wraps a
[`Session`](writing-sessions.md) for one robot. Interactive UX:
[`rosie drive`](../robots/mobile-base.md#rosie-drive).

Sibling capability clients (e.g. an arm helper) would wrap `Session` the same
way — there is no shared robot superclass.

## Construct

`with` auto-closes the session on exit. You can also keep a long-lived
instance and call `close()` yourself.

```python
from rosie import MobileRobot

# From robot.yaml (identity + connect + default teleop speeds)
with MobileRobot(config_path="robot.yaml") as bot:
    bot.wait_for_pose()
    bot.drive_to(1.0, 0.0)

# By id — no local robot.yaml (fleet mate, bridged ROS robot, …)
with MobileRobot(robot="car1", fleet="lab", connect="tcp/192.168.8.2:7447") as bot:
    bot.wait_for_pose()
    bot.teleop()

# Long-lived — call methods later; close when finished
bot = MobileRobot(robot="car1", fleet="lab", connect="tcp/192.168.8.2:7447")
bot.wait_for_pose()
bot.drive_to(1.0, 0.0)
bot.close()
```

### Constructor kwargs

| Kwarg | Role |
|-------|------|
| `robot` | Robot id for relative topics |
| `fleet` | Optional fleet id |
| `connect` | Zenoh locator (e.g. `tcp/127.0.0.1:7447`) |
| `name` | Session name (default `"mobile"`) |
| `config_path` | Optional `robot.yaml` — fills identity / connect / teleop defaults |
| `secure` | Prefer secure Session when no password is loaded from YAML |

### Identity resolution

1. Explicit `robot` / `fleet` / `connect` kwargs (when provided)
2. Else fields from `config_path` (`robot.yaml`) when set
3. Else `robot` from `ROSIE_ROBOT` (default `"robot"`)

Explicit kwargs win over YAML for any field you pass. You do **not** need a
copy of another robot’s `robot.yaml` on the laptop — only its id (and fleet /
connect) as seen on the bus.

## Methods

### Sense

| Method | Use when |
|--------|----------|
| `pose()` | Non-blocking read of the latest `pose` (may be `{}` until the first message). |
| `wait_for_pose(timeout_s=3)` | Bring-up: block until the robot is publishing pose (or return `None` on timeout). |

### Drive / navigate

| Method | Use when |
|--------|----------|
| `goto(x, y, goal_id=None)` | Fire-and-forget planar goal; you handle completion yourself via `nav_result` / `pose`. Returns `goal_id`. |
| `drive_to(x, y)` | Scripted demos: send a goal and **block** until matching `nav_result` (prints progress; Ctrl-C → `stop`). |
| `drive_route([(x,y), …])` | Visit several points in order — sequential `drive_to`, not a path planner. |
| `teleop(v_fwd=…, v_turn=…)` | Interactive WASD driving on this robot (same idea as `rosie teleop`). |
| `stop()` | Cancel motion now (motors stop; active goto → `nav_result` `canceled`). |

Navigation ladder (`goto` → `pose` progress → `nav_result`):
[Mobile base → Navigation helpers](../robots/mobile-base.md#navigation-helpers). Prefer `teleop()` on typical bridged ROS agents (see below).

### Setup / tune

| Method | Use when |
|--------|----------|
| `zero()` | Reset the pose origin to “here” (odometry zero), not an emergency stop. |
| `set_heading_source(imu=True\|False)` | Choose IMU vs encoder heading (`imu=None` toggles). Works on MCU and Linux when an IMU is configured. |
| `set_gains(kp=…, …)` | Live-tune onboard velocity PID (partial kwargs OK). Requires `control.velocity` (or DiffDriveStack’s always-on PID). |
| `get_gains()` | Ask the robot to publish current gains / wheel velocities on `control` (does not return them). |

### Camera

| Method | Use when |
|--------|----------|
| `set_camera_enable(True\|False)` | Turn camera streaming on/off (`cmd` `camera_enable`). |
| `snap(…)` | Capture one JPEG from `camera/compressed` (enables camera, saves under `captures/`). |
| `camera_live(…)` | Live preview window (OpenCV if installed; otherwise frame-size prints). |

Frames are independent JPEGs published at `camera.pub_hz` — see
[Camera](../robots/camera.md).

### Lifecycle

| Method | Use when |
|--------|----------|
| `close()` / `with MobileRobot(...)` | Always close when done. Prefer the context manager. |

## Bridged ROS robots

Typical [`rosie agent`](../robots/bridges.md) bridges `cmd_vel`, `pose`, and
`presence` only. Prefer `teleop()` or a raw `Session` for those robots until
`goto` / `nav_result` are bridged. Native MobileBase / DiffDriveStack robots
support the full nav helpers above.

## Related

- [Writing sessions](writing-sessions.md) — raw `Session`
- [Fleet](fleet.md) — fleet discovery / wait / estop
- [Mobile base](../robots/mobile-base.md) — shared contract, topics, `rosie drive`
- [Firmware](../robots/firmware.md) · [Linux run](../robots/linux-run.md) — platform assembly
- [Bridges](../robots/bridges.md) — `rosie agent`
