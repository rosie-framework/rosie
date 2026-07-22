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

## 3. Start the router

```bash
rosie router
```

Listens on `tcp/0.0.0.0:7447` using the packaged listen config (works for both
dedicated-AP fleets and solo SoftAP).

Check the install:

```bash
rosie doctor
```

## 4. Pick a path

### A. Host only — minimal pub/sub

No robot required. From the Rosie repo root:

```bash
python examples/minimal-pub-sub/talker.py
# another terminal
python examples/minimal-pub-sub/listener.py
```

Next for host apps: [Writing sessions](writing-sessions.md).

### B. Ground robot — DiffDriveStack

For a planar differential-drive MCU (ESP32). Install with MCU extras if you
have not already: `pip install -e "python[mcu]"`.

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot
# edit robot.yaml — pins, SSID/password, geometry
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
```

`rosie mcu init` writes `robot.yaml` and a thin sketch. The firmware is just:

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
rosie teleop --robot mybot          # WASD → cmd_vel only
rosie drive --config robot.yaml     # REPL: waypoints, teleop, camera, …
rosie mcu monitor
```

How to use the drive REPL: [Mobile base → Host](mobile-base.md#host).
Full checklist: [BYOR](byor.md). Control / YAML / topics: [Mobile base](mobile-base.md).
Raw `MobileBase` (custom motors / wiring) is an escape hatch there — not the
default path.

### C. Ground robot — Linux native (`rosie run`)

For a Pi / Jetson DIY base Rosie drives directly (no ROS). Install
`pip install -e "python[linux]"` on the robot (or use a BYO Python
`MotorDriver` with plain `pip install rosie`).

```bash
# robot.yaml with platform: linux + motors (tb6612 / pca9685 / python)
rosie run --config robot.yaml --dry-run
rosie run --config robot.yaml
# laptop: rosie teleop / viz / fleet list — same as MCU
```

Details: [Mobile base → Linux native](mobile-base.md#linux-native-rosie-run).
ROS robots use `rosie agent` instead: [Bridges](bridges.md).

## 5. Networking

Choose how the laptop and robot(s) share a LAN with the router from step 3.

### Fleet / dedicated AP (recommended)

For one or more robots (including heterogeneous types):

1. Power a **dedicated AP** (travel / pocket router) with a fixed SSID — avoid
   home/venue Wi‑Fi when you want portable demos.
2. Join the laptop and all robots to that SSID as **stations**.
3. `rosie router` on the laptop (or a Pi on the same LAN).
4. Point every robot (and host sessions) at `tcp/<router-host-ip>:7447`
   via firmware config / `ROSIE_CONNECT`.
5. `rosie fleet list --fleet <id>` / teleop as usual.
6. Optional: `rosie fleet wait --manifest …`, `rosie topic list --fleet <id>`,
   `rosie bag record --fleet <id> -o run.rosiebag` (or `.rosiebag.gz`),
   `rosie bag info run.rosiebag`.
7. Optional spatial view: `rosie viz --fleet <id>` (opens a local browser map
   of poses / trails). Solo SoftAP: `rosie viz --robot <id>`. Offline:
   `rosie viz --bag run.rosiebag` (optional `--start` / `--end` / `--key`
   filters, same as `rosie bag play`). Details: [Viz](viz.md).

Full detail: [Fleet networking](fleet-networking.md).

### Solo SoftAP fallback (one MCU)

When you have a single ESP32 and no travel router:

1. `pip install` + `rosie setup` (+ `rosie mcu setup`) on normal Wi‑Fi.
2. Join the **robot** SoftAP. Confirm host IP (often **192.168.4.2**).
3. `rosie router`
4. If the MCU finished connect retries before the router was up, **reset the board**.
5. Run host sessions / `rosie teleop --robot <id>`.

This is **one robot ↔ one host** only — not the multi-robot path.
Diagram: [Architecture](architecture.md).

## Environment defaults

| Variable | Meaning |
|----------|---------|
| `ROSIE_CONNECT` | Zenoh endpoint for host sessions (default `tcp/127.0.0.1:7447`). Set when the router is remote. MCU robots use `robot.yaml` `network.connect` (LAN IP). |
| `ROSIE_ROBOT` | Default robot id for sessions / `rosie teleop` |
| `ROSIE_FLEET` | Optional default fleet id |
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
| PlatformIO missing | `pip install "rosie[mcu]"` |
| `snap` / `cam` fails or prints “opencv not installed” | `pip install "rosie[camera]"` (OpenCV for host viewing only) |
| Publish/subscribe wrong keys | Use relative names under `Session(robot=...)`, or absolute `/...` ([Conventions](conventions.md)) |
| Firmware JSON publish fails / truncated | Payload exceeds ~384-byte MCU buffer ([Firmware](firmware.md)) |
| Trying to run two SoftAP cars at once | SoftAP is solo-only — use a [dedicated AP](fleet-networking.md) |

## Appendix: manual zenohd

If you prefer not to use `rosie setup` / `rosie router`:

```bash
# download from https://download.eclipse.org/zenoh/zenoh/ or GitHub releases
zenohd -c tools/zenoh.json5
```

MCU escape hatch: raw `pio …` from a PlatformIO robot directory. Details:
[Firmware](firmware.md).

## Next

- [Mobile base](mobile-base.md) — `robot.yaml`, DiffDriveStack, `rosie drive` / Host REPL
- [Bring Your Own Robot](byor.md) — full MCU bring-up checklist
- [Robots: native vs bridge](bridges.md) — `rosie agent` for ROS / commercial robots
- [Drivers](drivers.md) — inventory (`rosie drivers list`)
- [Fleet networking](fleet-networking.md) — dedicated AP, SoftAP fallback, discovery
- [Writing sessions](writing-sessions.md)
- [Viz](viz.md) — `rosie viz` browser map / bag scrub
- [Conventions](conventions.md) — topics, units, robot/fleet identity
- [Messages](messages.md) — std message catalog
- [Firmware](firmware.md)
- [Architecture](architecture.md)
- [Motivation](motivation.md) — purpose and Rosie vs ROS 2
