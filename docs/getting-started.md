# Getting started

## 1. Install Rosie

From the Rosie repo root (or any project):

```bash
pip install -e python
# host + MCU flash/build tooling:
# pip install -e "python[mcu]"
# Pi / Jetson GPIO / I2C for `rosie run`:
# pip install -e "python[linux]"
# host camera snap / live view in `rosie drive` (OpenCV):
# pip install -e "python[camera]"
# or heavy extras:
# pip install -e "python[mcu,camera,linux]"
```

This installs the `rosie` CLI, the Python client (`eclipse-zenoh`), and host tools
including `rosie viz` and `rosie bag export` (MCAP). Optional `[mcu]` adds
PlatformIO for MCU build/flash. Optional `[linux]` adds `lgpio` / `smbus2` for
built-in Linux drivers (`rosie run`). Optional `[camera]` adds OpenCV for
host-side JPEG viewing (`snap` / `cam` in `rosie drive`); robots can still
publish `camera/compressed` without it.

## 2. Set up the bus (once, while online)

Fleet / SoftAP networks often have **no internet**. Fetch `zenohd` before you
join an offline demo network:

```bash
rosie setup
```

This downloads a pinned `zenohd` into `~/.rosie/bin/` (checksum-verified).

## 3. Create a fleet, then start the router

A fleet is required — even for one robot. `fleet init` writes the host home
(`~/.rosie/fleets/<id>/`); it does **not** start zenohd.

```bash
rosie fleet init --fleet lab
rosie router --fleet lab
```

The router listens on `tcp/0.0.0.0:7447`. It will not create the fleet for you;
if the home is missing it exits and tells you to run `fleet init`.

Check the install:

```bash
rosie doctor
```

## 4. Pick a path

### A. Ground robot — MCU (`rosie mcu`)

For a planar differential-drive MCU (ESP32). Install with MCU extras if you
have not already: `pip install -e "python[mcu]"`.

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot --fleet lab
# edit robot.yaml — motors.driver / pins, SSID/password, geometry
# (default motors.driver: tb6612; also l298n, … — see Drivers)
rosie fleet add --fleet lab --from robot.yaml
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
```

`rosie mcu init` writes `robot.yaml` and a thin `DiffDriveStack` sketch:

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

Useful host commands once the robot is on the bus:

```bash
rosie teleop --robot mybot --fleet lab   # WASD → cmd_vel only
rosie drive --config robot.yaml     # REPL: waypoints, teleop, camera, …
rosie mcu monitor
```

How to use the drive REPL: [MobileRobot → rosie drive](host/mobile-robot.md#rosie-drive).
Full checklist: [BYOR](robots/byor.md). Control / YAML / topics: [Mobile base](robots/mobile-base.md).
Raw `MobileBase` is an escape hatch for chips not in the MCU inventory / stack —
not the default path.

### B. Ground robot — Linux native (`rosie run`)

For a Pi / Jetson DIY base Rosie drives directly (no ROS). Install
`pip install -e "python[linux]"` on the robot (or use a BYO Python
`MotorDriver` with plain `pip install rosie-framework`).

```bash
# robot.yaml with platform: linux + motors (tb6612 / pca9685 / python)
rosie run --config robot.yaml --dry-run
rosie run --config robot.yaml
# laptop: rosie teleop / viz / fleet list — same as MCU
# optional: rosie tune --config robot.yaml  (needs control.velocity)
```

Details: [Linux run](robots/linux-run.md).

### C. ROS / commercial robot (`rosie agent`)

Keep the vendor ROS 2 stack on the robot; run **`rosie agent`** beside it so
the fleet sees the same `cmd_vel` / `pose` / `presence` contract (and `goto` /
`nav_result` when Nav2 is up). Laptop stays Rosie-only (no ROS).

```bash
# on the robot (after ROS bring-up so /cmd_vel and /odom exist)
python3 -m venv --system-site-packages ~/rosie-venv
source ~/rosie-venv/bin/activate
pip install rosie-framework
# source /opt/ros/$ROS_DISTRO/setup.bash

rosie agent init --robot turtle1 --fleet lab
# optional: --connect tcp/<router-host-ip>:7447  (skip if connect: auto works)
# optional: --profile turtlebot4
rosie agent doctor
rosie agent run
```

From the laptop: `rosie teleop --robot turtle1`, `rosie fleet list`, `rosie viz`
— same tools as native robots. `rosie drive` needs Nav2 on the robot. Full
detail: [Bridges](robots/bridges.md).

## 5. Networking

Choose how the laptop and robot(s) share a LAN with the router from step 3.

### Dedicated AP (recommended)

For one or more robots (including heterogeneous types):

1. `rosie fleet init --fleet <id>` (once, before the router).
2. Power a **dedicated AP** (travel / pocket router) with a fixed SSID — avoid
   home/venue Wi‑Fi when you want portable research and field deployments.
3. Join the laptop and all robots to that SSID as **stations**.
4. `rosie router --fleet <id>` on the router host (laptop, or a Pi on the same LAN).
5. Robots: `connect: auto` (Linux scout / MCU codegen) or an explicit
   `tcp/<router-host-ip>:7447`. See [How robots find the router](fleet/networking.md#how-robots-find-the-router).
6. `rosie fleet list --fleet <id>` / teleop as usual.
7. Optional: `rosie fleet wait --manifest …`, `rosie topic list --fleet <id>`,
   `rosie bag record --fleet <id> -o run.rosiebag` (or `.rosiebag.gz`),
   `rosie bag info run.rosiebag`.
8. Optional spatial view: `rosie viz --fleet <id>` (opens a local browser map
   of poses / trails). Offline: `rosie viz --bag run.rosiebag` (optional
   `--start` / `--end` / `--key` filters, same as `rosie bag play`).
   Details: [Viz](host/viz.md).

Full detail: [Fleet networking](fleet/networking.md). Membership:
[Fleet management](fleet/management.md). Open vs secure modes:
[Security](fleet/security.md).

### One-robot SoftAP (still a fleet)

When you have a single ESP32 and no travel router. The robot still belongs
to a fleet (`{fleet}/{robot}/pose`):

1. `pip install` + `rosie setup` (+ `rosie mcu setup`) on normal Wi‑Fi.
2. `rosie fleet init --fleet lab` (if you have not already).
3. Join the **robot** SoftAP. Confirm host IP (often **192.168.4.2**).
4. `rosie router --fleet lab`
5. If the MCU finished connect retries before the router was up, **reset the board**.
6. Run host sessions / `rosie teleop --robot <id> --fleet lab`.

This is **one robot ↔ one host** only — two SoftAP cars need a dedicated AP.
Diagram: [Architecture](architecture.md).

## Environment defaults

| Variable | Meaning |
|----------|---------|
| `ROSIE_CONNECT` | Zenoh endpoint for host sessions (default `tcp/127.0.0.1:7447`). Set when the router is remote, or `auto` to scout. MCU / Linux robots use `network.connect` / `agent.yaml` `connect` — see [How robots find the router](fleet/networking.md#how-robots-find-the-router). |
| `ROSIE_ROBOT` | Default robot id for sessions / `rosie teleop` |
| `ROSIE_FLEET` | Default fleet id for host tools / Session (required unless `--fleet` or yaml) |
| `ROSIE_ZENOHD` | Override path to a `zenohd` binary |
| `ROSIE_HOME` | Cache dir (default `~/.rosie`) |
| `ROSIE_PORT` | Default serial port for `rosie mcu flash` / `rosie mcu monitor` |

More identity and topic rules: [Conventions](conventions.md).

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Zenoh session open, but no `pose` | Host/robot not on the same Wi‑Fi, wrong `ROSIE_CONNECT` / MCU locator, or MCU never connected |
| MCU connect attempts fail then stop | Start `rosie router` after joining the shared network, then reset the board |
| `pip` / `rosie setup` fails offline | Demo AP often has no internet — install and `rosie setup` first |
| `zenohd not found` | Run `rosie setup`, or put `zenohd` on PATH / set `ROSIE_ZENOHD` |
| PlatformIO missing | `pip install "rosie-framework[mcu]"` |
| `snap` / `cam` fails or prints “opencv not installed” | `pip install "rosie-framework[camera]"` (OpenCV for host viewing only) |
| Publish/subscribe wrong keys | Use relative names under `Session(robot=..., fleet=...)`, or absolute `/...` ([Conventions](conventions.md)) |
| Firmware JSON publish fails / truncated | Payload exceeds ~384-byte MCU buffer ([Firmware](robots/firmware.md)) |
| Trying to run two SoftAP cars at once | SoftAP is one-robot-only — use a [dedicated AP](fleet/networking.md) |


## Next

- [Mobile base](robots/mobile-base.md) — `robot.yaml`, DiffDriveStack, `rosie drive` / Host REPL
- [Bring Your Own Robot](robots/byor.md) — full MCU bring-up checklist
- [Robots: native vs bridge](robots/bridges.md) — `rosie agent` for ROS / commercial robots
- [Drivers](robots/drivers.md) — inventory (`rosie drivers list`)
- [Fleet networking](fleet/networking.md) — dedicated AP, SoftAP fallback, discovery
- [Fleet management](fleet/management.md) — init / add / router day-to-day
- [Security](fleet/security.md) — fleet-open vs fleet-secure, allowlist, ESP32 limits
- [Writing sessions](host/writing-sessions.md)
- [MobileRobot](host/mobile-robot.md) — host MobileBase client API
- [Fleet](host/fleet.md) — host fleet discovery / wait / estop API
- [Viz](host/viz.md) — `rosie viz` browser map / bag scrub
- [Conventions](conventions.md) — topics, units, robot/fleet identity
- [Messages](messages.md) — std message catalog
- [Firmware](robots/firmware.md)
- [Architecture](architecture.md)
- [Motivation](motivation.md) — purpose and Rosie vs ROS 2
