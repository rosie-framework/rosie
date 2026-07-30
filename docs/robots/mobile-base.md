# Mobile base

Shared behavior contract for **planar ground robots** (differential drive in
v1). Transport remains `rosie::Session` / Python `Session`. Platform assembly
differs — MCU uses `DiffDriveStack`, Linux uses `rosie run` — but both honor
the same topics, modes, deadman, goto, and optional velocity PID.

## Layers

Think of it as a stack: you write config; each platform assembles the shared
behavior layer; hardware sits at the bottom.

```mermaid
flowchart TB
  subgraph mcu [MCU]
    yamlM["robot.yaml to robot_config.h"]
    stack["DiffDriveStack"]
  end
  subgraph linux [Linux]
    yamlL["robot.yaml at runtime"]
    run["rosie run"]
  end
  shared["Shared behavior: topics, modes, deadman, goto, cmd ops"]
  kin["Kinematics: twist to channels, wheel vel, odometry"]
  vel["VelocityController: optional wheel PID"]
  motors["MotorDriver: channels to PWM"]
  yamlM --> stack --> shared
  yamlL --> run --> shared
  shared --> kin --> vel --> motors
```

- **MCU assembly** — `robot.yaml` → `robot_config.h` codegen and
  `DiffDriveStack` wire motors, sensors, Wi‑Fi, Zenoh, `MobileBase`, and
  SerialShell. Details: [Firmware](firmware.md).
- **Linux assembly** — `robot.yaml` (`platform: linux`) read at runtime by
  `rosie run` / `MobileBaseRuntime`. Details: [Linux run](linux-run.md).
- **Shared behavior** — topics, IDLE / MANUAL / AUTO, teleop deadman, goto,
  and `cmd`. Teleop and goto both produce a body Twist `(v, w)` and share one
  actuation path through the layers below.
  - **Kinematics** — steering geometry: Twist ↔ feedforward channels + wheel
    velocities + odometry (DiffDrive today; mecanum / ackermann later).
  - **`VelocityController`** — optional closed-loop correction between
    kinematics outputs and motors. Default PID with gains `0,0,0` ≈ open-loop
    passthrough; if no controller is attached, kinematics channels go straight
    to the motor driver. Select via `control.velocity.type` (v1: `pid` only).
  - **`MotorDriver`** — channels in `[-1, 1]` → PWM. Inventory:
    [Drivers](drivers.md).

### Platform differences

| Concern | MCU | Linux (`rosie run`) |
|---------|-----|---------------------|
| Config apply | codegen + reflash | restart `rosie run` |
| Assembly | `DiffDriveStack` | `MobileBaseRuntime` |
| Camera | yes (`camera/compressed`) | yes (`camera/compressed`) |
| Range (ToF) | yes (`range/<id>`) | yes (`range/<id>`) |
| SerialShell | yes (USB) | no |
| Dead-reckoning without encoders | no (ticks required) | yes |

## Configuring control

Twist sources and the shared actuation path are described in [Layers](#layers).
Configure gains in YAML; tune live on either platform.

### Control loop timing

Motion callbacks do **not** drive the motors. They latch the latest request
with a local arrival stamp; the next control tick applies it (mode change +
Twist → motors). Several `cmd_vel` messages between ticks overwrite the latch;
only the last one is used. Custom `cmd` handlers (e.g. `set_gains`) may run
immediately in the callback. `control.dt_ms` (default `20`) sets the control
rate.

**Command precedence:** the tick honors arrival order. A `cmd_vel` older than
the latest `stop` / `zero` does not re-enter MANUAL. While navigating, a `goto`
with the same `goal_id` is ignored (duplicate); a lower id is ignored as stale;
a higher id preempts. Delivery classes for pubs (`nav_result` = COMMAND,
camera = BULK, telemetry = STREAM): [Conventions → Delivery and validity](../conventions.md#delivery-and-validity).

Host `cmd_vel` (MANUAL) or onboard goto (AUTO) produces a body Twist `(v, w)`.
That Twist goes through kinematics, then an optional `VelocityController`,
then the motor driver. Teleop and goto share that path today.

Platform mechanisms (Arduino `spin()` vs Python main loop):
[Firmware](firmware.md#control-loop) · [Linux run](linux-run.md#control-loop).

```yaml
control:
  goto:                    # pose → Twist
    kp_linear: 0.8
    kp_angular: 1.5
    v_max: 0.35
    w_max: 1.5
  velocity:                # omit or kp=ki=kd=0 for open-loop
    type: pid
    kp: 0.0
    ki: 0.0
    kd: 0.0
    i_clamp: 0.5
  control_hz: 5            # control topic rate when velocity PID attached
```

Default velocity gains are **zero** (same feel as open-loop). Non-zero
starter gains are robot-specific — tune with `rosie tune`. Requires a
`control.velocity` section (or DiffDriveStack, which always attaches a PID).

### Live tuning

```bash
rosie tune --config robot.yaml          # interactive
rosie tune set --config robot.yaml --kp 0.3
rosie tune save --config robot.yaml     # persist live gains into YAML
# MCU: reflash to bake saved defaults
# Linux: restart `rosie run` to load YAML defaults
```

Cmd ops: `set_gains` `{kp,ki,kd,i_clamp}` (partial OK), `get_gains`. Telemetry on
`control` (gains + target/meas wheel velocities) at `control.control_hz`
(default 5 Hz), plus immediately after gain ops.

## `robot.yaml`

See the reference car’s `robot.yaml`. Required: `robot`, `network`, `base`,
`motors`. Optional: `encoders`, `imu`, `camera`, `range`, `control`.

Inventory: [Drivers](drivers.md) / `rosie drivers list` (`--platform mcu|linux`).

Set `platform: mcu` (default) or `platform: linux`. Shared sections (`robot`,
`fleet`, `network.connect`, `base`, `control`, `range.sensors` layout) port
across platforms; the `motors` / `encoders` / `imu` / `range` pin and bus
blocks are platform-specific (ESP32 GPIO vs Pi BCM / I2C).

Bring-up: [BYOR](byor.md) · MCU: [Firmware](firmware.md) · Linux: [Linux run](linux-run.md).

## Standard topics (MobileBase)

| Topic | Direction | Notes |
|-------|-----------|-------|
| `cmd_vel` | host → robot | `Twist` `{v,w}` |
| `goto` | host → robot | `{x,y,goal_id?}` meters — latest goal wins |
| `nav_result` | robot → host | one-shot `{goal_id,status,x?,y?}` when a goto ends |
| `cmd` | host → robot | `stop`, `zero`, `set_gains`, `get_gains`, `heading_source`, plus custom ops |
| `pose` | robot → host | `x,y,theta` plus `mode`, `navigating`, `dist`, `goal_id` while navigating; `imu_ok` / `imu_heading` when IMU present |
| `control` | robot → host | velocity gains + target/meas wheel vel (when controller attached) |
| `encoders` | robot → host | cumulative ticks (`EncoderTicks`) when `encoders.pub_hz` set |
| `imu` | robot → host | 6-axis `Imu` (`accel_*` m/s², `gyro_*` rad/s) when `imu.pub_hz` set |
| `range/<id>` | robot → host | `Range` (`id`, raw `range`, `range_median`, min/max, `ok`) per sensor in `range.sensors` |
| `presence` | robot → host | heartbeat |
| `log` | robot → host | status lines |
| `camera/compressed` | robot → host | JPEG bytes (if camera in YAML) |

## Host

With the robot on the bus and `rosie router` running:

```bash
rosie drive --config robot.yaml
rosie teleop --robot mybot
rosie tune --config robot.yaml
```

Drive REPL includes optional camera `snap` / `cam` when the robot publishes
JPEG. For the OpenCV viewer on the host: `pip install "rosie-framework[camera]"` (robots
can publish `camera/compressed` without that extra). Full camera setup:
[Camera](camera.md).

### Navigation helpers

Onboard nav is **one goal at a time**:

| Topic / API | Role |
|-------------|------|
| `goto` / `MobileRobot.goto` | **Goal** — publish `{x,y,goal_id}` (fire-and-forget) |
| `pose` | **Progress** — `navigating`, `dist`, `goal_id` while AUTO |
| `nav_result` | **Done** — `{goal_id,status}` once (`succeeded` / `canceled`; `aborted` is reserved — hosts must tolerate it, robots do not currently emit it) |
| `cmd` `stop` | **Cancel** — stops motors; yields `nav_result` `canceled` if a goto was active |
| `MobileRobot.drive_to` | **Blocking helper** — `goto` + wait for matching `nav_result` |
| `MobileRobot.drive_route` | **Convenience** — sequential `drive_to` (not a path planner) |
| `rosie drive` | **REPL** — interactive prompt over those helpers |

Latest `goto` preempts any in-progress goal (previous attempt gets `canceled`).
Compose retries or tasks-at-waypoint yourself on top of `goto` / `drive_to`.
Do not treat `drive_route` as autonomy infrastructure.

### `rosie drive`

Interactive REPL over `rosie.MobileRobot` for a MobileBase robot.
Uses `robot.yaml` for identity (or `--robot` / `ROSIE_ROBOT`). Optional:
`--fleet`, `--connect`, `--dir` (search for `robot.yaml`).

```bash
rosie drive --config robot.yaml
# or from a robot project directory:
rosie drive
```

At the `target>` prompt:

| Input | Action |
|-------|--------|
| `x y [x y …]` | `drive_route` — sequential goals (meters in the pose frame) |
| `teleop` | Nested WASD teleop (same bindings as `rosie teleop`) |
| `snap` | Capture a camera still (if camera configured) |
| `cam` | Live camera view |
| `zero` | Request pose zero |
| `imu` | Toggle heading source |
| `stop` | Emergency stop |
| `quit` | Exit |

`rosie teleop --robot <id>` is the dedicated WASD → `cmd_vel` tool when you
only want keyboard driving (no waypoint REPL).

### `rosie tune`

Live velocity-PID tuning — see [Live tuning](#live-tuning) above.

### Python (`rosie.MobileRobot`)

Prefer `drive_to` (or `goto`) in scripts; use `drive_route` only as a short
convenience:

```python
from rosie import MobileRobot
with MobileRobot(config_path="robot.yaml") as bot:
    bot.wait_for_pose()
    bot.set_gains(kp=0.3)   # requires control.velocity / attached PID
    bot.drive_to(1.0, 0.0)
```

Constructor kwargs, identity without `robot.yaml`, and the full method list:
[MobileRobot](../host/mobile-robot.md). Raw `Session`:
[Writing sessions](../host/writing-sessions.md).

## Related

- [BYOR](byor.md) · [Firmware](firmware.md) · [Linux run](linux-run.md) · [Drivers](drivers.md) · [Camera](camera.md) · [Bridges](bridges.md) · [Conventions](../conventions.md) · [MobileRobot](../host/mobile-robot.md) · [Writing sessions](../host/writing-sessions.md)
