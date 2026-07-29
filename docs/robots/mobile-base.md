# Mobile base

Opt-in firmware + host layer for **planar ground robots** (differential drive in
v1). Transport remains `rosie::Session` / Python `Session`; `MobileBase` /
`DiffDriveStack` add drivers, kinematics, deadman, goto, and standard topics.

## Layers

Think of it as a stack: you write config + a thin sketch; Rosie fills in the
middle; hardware sits at the bottom.

```mermaid
flowchart TB
  yaml["robot.yaml → robot_config.h"]
  stack["DiffDriveStack — YAML wiring"]
  mb["MobileBase — topics, modes, deadman, goto"]
  kin["BaseKinematics — Twist ↔ channels + odom"]
  vel["VelocityController — optional wheel PID"]
  motors["MotorDriver — channels → PWM"]

  yaml --> stack
  stack --> mb
  mb --> kin
  kin --> vel
  vel --> motors
```

- **`robot.yaml` → `robot_config.h`** — declarative identity, network, pins,
  geometry, gains, and feature flags. What you edit; codegen feeds the stack.
- **`DiffDriveStack`** — YAML-driven **default assembly** for diff-drive MCUs:
  constructs the selected motors, optional encoders/IMU/camera, kinematics,
  velocity PID, Wi‑Fi / Zenoh / `MobileBase`, and SerialShell from `robot.yaml`.
  Not the behavior layer — skip it only for chips the inventory/stack does not
  cover yet. Linux `rosie run` skips it entirely and mirrors `MobileBase` from
  YAML. Beside the control path below, the stack also wires encoder/IMU hooks
  and optional camera publish.
- **`MobileBase`** — shared **behavior** over Session: topics, IDLE/MANUAL/AUTO,
  teleop deadman, goto, and `cmd`. Holds refs to kinematics, an optional
  velocity controller, and the motor driver; used by both the MCU stack and
  Linux `rosie run`. Teleop and goto both produce a body Twist `(v, w)` and
  currently share one actuation path through the layers below; other modes may
  grow their own entry points later.
  - **`BaseKinematics`** — steering geometry: Twist ↔ feedforward channels +
    wheel velocities + odometry (DiffDrive today; mecanum / ackermann later).
  - **`VelocityController`** — optional closed-loop correction between
    kinematics outputs and motors. Default PID with gains `0,0,0` ≈ open-loop
    passthrough; if no controller is attached, kinematics channels go straight
    to the motor driver.
  - **`MotorDriver`** — channels in `[-1, 1]` → PWM. MCU inventory: TB6612,
    L298N (see [Drivers](drivers.md)); BYO chips use raw `MobileBase`.

Steering variants plug in as new kinematics; `MobileBase` stays shared. Other
velocity algorithms implement `VelocityController` and select via
`control.velocity.type` (v1: `pid` only).

## What you write

1. **`robot.yaml`** — identity, network, pins, geometry, gains.
2. **Thin `main.cpp`** using **`DiffDriveStack`** (recommended), or raw
   `MobileBase` for custom wiring.
3. Optional custom `cmd` ops via `stack.base().onCmd(...)`.

Scaffold a new project:

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot
# edit robot.yaml pins / SSID
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
```

## Recommended firmware (`DiffDriveStack`)

Include the generated header, then the stack:

```cpp
#include <Arduino.h>
#include "generated/robot_config.h"
#include <rosie/diff_drive_stack.h>

static rosie::DiffDriveStack g_stack;

void setup() {
  Serial.begin(115200);
  delay(300);
  // Optional: g_stack.base().onCmd("my_op", handler);
  g_stack.begin();
}

void loop() {
  g_stack.loop();
}
```

`rosie mcu build` / `gen-config` regenerates `robot_config.h` from `robot.yaml`.
`DiffDriveStack` wires the **selected** motors (`motors.driver`), optional
encoders / IMU / camera, DiffDrive kinematics, Wi‑Fi, Zenoh, SerialShell,
`MobileBase`, and a `PidVelocityController` (default gains `0,0,0` = open-loop
feedforward). See [Drivers](drivers.md) for supported ids and pin keys
(e.g. TB6612 `pwmA`/`ain1`… vs L298N `ena`/`in1`…).

Accessors: `stack.base()`, `stack.motors()` (`MotorDriver&`), `stack.kinematics()`,
`stack.velocityController()`; plus `stack.encoders()` / `stack.imu()` /
`stack.camera()` when those sections are present in YAML.

## Alternative: raw `MobileBase`

If the chip is not in the MCU inventory (or not wired into `DiffDriveStack`
yet), implement `MotorDriver` / kinematics yourself and pass them into
`MobileBase`. Optionally attach a `VelocityController`. Keep using relative
topics so `rosie teleop` / `rosie drive` still work.

## Configuring control

Twist sources and the shared actuation path under `MobileBase` are described in
[Layers](#layers). Configure gains in YAML; tune live without reflashing.

Host `cmd_vel` (MANUAL) or onboard goto (AUTO) produces a body Twist `(v, w)`.
That Twist goes through `BaseKinematics`, then an optional `VelocityController`,
then `MotorDriver`. Teleop and goto share that path today.

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
```

Default velocity gains are **zero** (same feel as open-loop). Non-zero
starter gains are robot-specific — tune with `rosie tune`.

### Live tuning

```bash
rosie tune --config robot.yaml          # interactive
rosie tune set --config robot.yaml --kp 0.3
rosie tune save --config robot.yaml     # persist live gains into YAML
rosie mcu flash                         # bake saved defaults
```

Cmd ops: `set_gains` `{kp,ki,kd,i_clamp}` (partial OK), `get_gains`. Telemetry on
`control` (gains + target/meas wheel velocities).

Custom inner loop: implement `VelocityController` and
`base.setVelocityController(&ctrl)` (or inject via BYO MobileBase).

## `robot.yaml`

See the reference car’s `robot.yaml`. Required: `robot`, `network`, `base`,
`motors`. Optional: `encoders`, `imu`, `camera`, `control`.

Inventory: [Drivers](drivers.md) / `rosie drivers list` (`--platform mcu|linux`).

Set `platform: mcu` (default) or `platform: linux`. Shared sections (`robot`,
`fleet`, `network.connect`, `base`, `control`) port across platforms; the
`motors` / `encoders` / `imu` blocks are platform-specific (ESP32 GPIO vs Pi BCM
/ I2C).

## Linux native (`rosie run`)

On a Pi or Jetson, Rosie can drive the base directly (no ROS) from `robot.yaml`:

```yaml
platform: linux
robot: pi1
fleet: lab
network:
  connect: tcp/192.168.8.2:7447
base:
  type: diff_drive
  wheel_diameter: 0.068
  wheel_base: 0.13
  ticks_per_rev: 1440
motors:
  driver: tb6612          # same chip as the ESP32 car; pins are Pi BCM
  pins: { pwmA: 12, ain1: 5, ain2: 6, pwmB: 13, bin1: 20, bin2: 21 }
  pwm: { freq: 20000, min: 0.1, max: 1.0 }
# encoders:               # optional; without them, pose is dead-reckoned
#   driver: gpio_quadrature
#   pins: { left: [17, 18], right: [22, 23] }
#   pub_hz: 10            # optional: EncoderTicks on encoders topic
# imu:
#   chip: mpu6050
#   i2c: { bus: 1, addr: 0x68 }
#   pub_hz: 10            # optional: Imu on imu topic
control:
  dt_ms: 20
  teleop: { timeout_ms: 400, kv: 180, kw: 40 }
  goto: { kp_linear: 0.8, kp_angular: 1.5, v_max: 0.35, w_max: 1.5 }
  pose_hz: 20
  presence_hz: 1
```

```bash
pip install "rosie-framework[linux]"          # built-in tb6612 / gpio / mpu6050 / pca9685
rosie run --config robot.yaml --dry-run
rosie run --config robot.yaml
```

The runtime mirrors firmware `MobileBase`: `cmd_vel`, `goto` / `nav_result`,
`cmd` (`stop` / `zero`), `pose`, `presence`, teleop deadman, and optional
`encoders` / `imu` topics when `pub_hz` is set. Laptop tools
(`teleop`, `viz`, `fleet`, `MobileRobot`) work unchanged.

**BYO driver** (no `rosie-framework[linux]` needed):

```yaml
motors:
  driver: python
  class: mypkg.motors:MyMotorDriver   # set_channels / stop / close
```

`rosie drivers list --platform linux` lists inventory ids. Camera on Linux is
not supported yet.

## Standard topics (MobileBase)

| Topic | Direction | Notes |
|-------|-----------|-------|
| `cmd_vel` | host → robot | `Twist` `{v,w}` |
| `goto` | host → robot | `{x,y,goal_id?}` meters — latest goal wins |
| `nav_result` | robot → host | one-shot `{goal_id,status,x?,y?}` when a goto ends |
| `cmd` | host → robot | `stop`, `zero`, `set_gains`, `get_gains`, plus custom ops |
| `pose` | robot → host | `x,y,theta` plus `mode`, `navigating`, `dist`, `goal_id` while navigating |
| `control` | robot → host | velocity gains + target/meas wheel vel (when controller attached) |
| `encoders` | robot → host | cumulative ticks (`EncoderTicks`) when `encoders.pub_hz` set |
| `imu` | robot → host | 6-axis `Imu` (`accel_*` m/s², `gyro_*` rad/s) when `imu.pub_hz` set |
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
can publish `camera/compressed` without that extra).

### Navigation helpers

Onboard nav is **one goal at a time**:

| Topic / API | Role |
|-------------|------|
| `goto` / `MobileRobot.goto` | **Goal** — publish `{x,y,goal_id}` (fire-and-forget) |
| `pose` | **Progress** — `navigating`, `dist`, `goal_id` while AUTO |
| `nav_result` | **Done** — `{goal_id,status}` once (`succeeded` / `canceled` / `aborted`) |
| `cmd` `stop` | **Cancel** — stops motors; yields `nav_result` `canceled` if a goto was active |
| `MobileRobot.drive_to` | **Blocking helper** — `goto` + wait for matching `nav_result` |
| `MobileRobot.drive_route` | **Convenience** — sequential `drive_to` (not a path planner) |
| `rosie drive` | **REPL** — interactive prompt over those helpers |

Latest `goto` preempts any in-progress goal (previous attempt gets `canceled`).
Compose retries or tasks-at-waypoint yourself on top of `goto` / `drive_to`.
Do not treat `drive_route` as autonomy infrastructure.

### `rosie drive`

Interactive REPL over `rosie.MobileRobot` for a MobileBase / DiffDriveStack robot.
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
    bot.set_gains(kp=0.3)
    bot.drive_to(1.0, 0.0)
```

Constructor kwargs, identity without `robot.yaml`, and the full method list:
[MobileRobot](../host/mobile-robot.md). Raw `Session`:
[Writing sessions](../host/writing-sessions.md).

## Related

- [BYOR](byor.md) · [Firmware](firmware.md) · [Drivers](drivers.md) · [Bridges](bridges.md) · [Conventions](../conventions.md) · [MobileRobot](../host/mobile-robot.md) · [Writing sessions](../host/writing-sessions.md)
