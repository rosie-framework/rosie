# Bring Your Own Robot (BYOR)

Checklist for standing up a new **native** robot on Rosie — one Rosie drives
directly (MCU firmware or Linux `rosie run`). For a **commercial / ROS robot**
you'd rather not rewrite (e.g. TurtleBot), keep its stack and run **`rosie
agent`** on the robot: [Robots: native vs bridge](bridges.md).

For shared names and units, see [Conventions](conventions.md). For networking,
see [Fleet networking](fleet-networking.md). For the batteries-included ground
base path, see [Mobile base](mobile-base.md) and [Drivers](drivers.md).

## Choose a platform

| Platform | Config | On the robot |
|----------|--------|--------------|
| **MCU** (ESP32, …) | `robot.yaml` (`platform: mcu`, default) | `rosie mcu init` / `setup` / `flash` |
| **Linux** (Pi, Jetson, DIY) | `robot.yaml` (`platform: linux`) | `rosie run --config robot.yaml` |

Shared sections (`robot`, `fleet`, `network.connect`, `base`, `control`) port
across platforms. The `motors` / `encoders` / `imu` blocks are platform-specific
(ESP32 GPIO vs Pi BCM / I2C). Inventory: `rosie drivers list --platform mcu|linux`.

---

# MCU path

## 1. Install Rosie

```bash
pip install -e "/path/to/rosie/python[mcu]"           # flash / build
# pip install -e "/path/to/rosie/python[mcu,camera]"  # + OpenCV for drive snap/cam
rosie setup                 # fetch zenohd while online
```

## 2. Scaffold the project

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot
```

That writes `robot.yaml`, a thin `DiffDriveStack` `src/main.cpp`, links
`lib/rosie`, and generates `src/generated/robot_config.h`.

Or from an existing folder: `rosie mcu setup` after you add `robot.yaml`.

## 3. Edit `robot.yaml`

Set pins, SSID/password, geometry, and gains. Inventory of driver ids:
`rosie drivers list` / [Drivers](drivers.md).

You do **not** hand-edit `ROSIE_*` constants — regenerate with
`rosie mcu gen-config` (also runs on every `rosie mcu build`).

## 4. Firmware

Default sketch (from `rosie mcu init`):

```cpp
#include "generated/robot_config.h"
#include <rosie/diff_drive_stack.h>

static rosie::DiffDriveStack g_stack;

void setup() {
  Serial.begin(115200);
  delay(300);
  g_stack.begin();
}

void loop() {
  g_stack.loop();
}
```

Optional: `g_stack.base().onCmd("my_op", handler);` before `begin()`.

```bash
rosie mcu build
rosie mcu flash
rosie mcu monitor
```

Raw `rosie::Session` / `MobileBase` remain valid for advanced / non-diff-drive
robots.

## 5. Host side

```bash
rosie drive --config robot.yaml     # REPL: waypoints, teleop, camera, …
rosie teleop --robot mybot          # WASD only
rosie tune --config robot.yaml      # optional: live velocity PID
```

Drive REPL commands, flags, and the Python `MobileRobot` API:
[Mobile base → Host](mobile-base.md#host).

## 6. Bring-up order

### Fleet (dedicated AP)

1. Install + `rosie setup` (+ `rosie mcu setup`) on normal internet.
2. Power the dedicated AP; join laptop + robots as stations (`network.mode: station`).
3. `rosie router` on the laptop (or Pi).
4. Confirm each robot’s Zenoh locator; reset MCUs if needed.
5. `rosie fleet list --fleet <id>` / `rosie drive` / teleop.

### Solo SoftAP fallback

1. Install + `rosie setup` on normal Wi‑Fi.
2. Join the robot SoftAP; confirm host IP (often `192.168.4.2`).
3. `rosie router`
4. Reset the MCU if it raced ahead of the router.
5. `rosie drive` / teleop.

## 7. Escape hatch (MCU)

Chip not in the inventory? Implement `MotorDriver` (or sensor helpers) in your
project and construct `MobileBase` yourself (skip `DiffDriveStack`). Document
custom `cmd` ops in your robot README.

## 8. What goes in the robot README

- Network mode, robot id, optional fleet, Zenoh locator
- That config lives in `robot.yaml`
- Board / `rosie mcu flash` notes (MCU) or `rosie run` notes (Linux)
- Any custom `cmd` ops beyond MobileBase defaults (`stop`, `zero`, `set_gains`, …)
- Whether velocity PID is used (`control.velocity`) and how to retune

---

# Linux path (`rosie run`)

On a Pi or Jetson, Rosie drives the base from the same `robot.yaml` shape, with
`platform: linux` and Linux drivers (no codegen, no ROS).

## L1. Install

```bash
pip install "rosie[linux]"   # built-in tb6612 / gpio_quadrature / mpu6050 / pca9685
# or: pip install rosie      # BYO Python MotorDriver only
```

## L2. Write `robot.yaml`

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
  driver: tb6612
  pins: { pwmA: 12, ain1: 5, ain2: 6, pwmB: 13, bin1: 20, bin2: 21 }
  pwm: { freq: 20000, min: 0.1, max: 1.0 }
control:
  dt_ms: 20
  teleop: { timeout_ms: 400 }
  pose_hz: 20
  presence_hz: 1
```

Omit `encoders` for dead-reckoning pose (optional IMU yaw). Full example:
[Mobile base → Linux native](mobile-base.md#linux-native-rosie-run).

## L3. BYO motor driver

```yaml
motors:
  driver: python
  class: mypkg.motors:MyMotorDriver
```

Implement `set_channels(channels)`, `stop()`, and `close()`. Optional
`from_config(cls, config)` classmethod. No `rosie[linux]` required for BYO.

## L4. Run

```bash
rosie run --config robot.yaml --dry-run   # validate + probe drivers
rosie run --config robot.yaml             # foreground control loop
```

Laptop: `rosie teleop`, `rosie viz`, `rosie fleet list` — same as MCU. Manual
`systemd` / `nohup` for now (unit generation deferred).
