# Rosie

<p align="center">
  <img src="assets/rosie-icon.png" alt="Rosie" width="160" />
</p>

Rosie is the easy **fleet layer** for mixed robots — MCU, Linux, and ROS —
from a normal laptop. Lightweight to install, low learning curve, and built so
multi-robot teams are first-class whether each robot runs Rosie **natively** or
uses another stack (e.g. ROS2) behind a thin **bridge**.

## Goals

1. **Robot fleets are first-class** — robot and fleet are real identity (not
   topic prefixes). Discover, wait, teleop, viz, and bag the whole team from
   one laptop on a brokered bus. This is why Rosie exists.
2. **Easy to get started** — low learning curve: `pip install`, one bus
   (`rosie router`), one robot description file, a small CLI. Drive a car or
   stand up a team in minutes without DDS, colcon, or an Ubuntu robot PC on
   the laptop.
3. **One fleet across backends** — MCU (ESP32 firmware), Linux robots (Pi /
   Jetson), and host laptops (macOS, Linux, Windows). Robots join **natively**
   (`robot.yaml` + firmware or `rosie run`) or via a **bridge** (`rosie agent`
   in front of ROS 2 / another backend). Membership and tooling span those
   paths; Rosie does not require rewriting every robot.

Either way, a robot is just an id under `{fleet}/{robot}/…`. Same laptop tools
drive a heterogeneous team. Native vs bridge decision:
[docs/bridges.md](docs/bridges.md). Deeper “why Rosie”:
[docs/motivation.md](docs/motivation.md).

## Install

```bash
pip install -e python              # host: Session, CLI, router, viz, bags / MCAP export
pip install -e "python[mcu]"       # + MCU build / flash (PlatformIO under the hood)
pip install -e "python[linux]"     # + Pi/Jetson GPIO / I2C drivers for `rosie run`
pip install -e "python[camera]"    # + OpenCV for host camera snap / live view
# or: pip install -e "python[mcu,camera,linux]"

rosie setup      # fetch zenohd once (while online)
rosie router     # start the bus
rosie doctor     # sanity-check the host
```

Details: [docs/getting-started.md](docs/getting-started.md). Notices: [NOTICE](NOTICE).

## How you work with Rosie

| Piece | Role |
| ----- | ---- |
| `rosie` **CLI** | Bus (`router`, `doctor`), robots (`teleop`, `drive`, `tune`, `run`), fleets, topics, bags, ROS bridge (`agent`), MCU flash |
| `robot.yaml` | Native robots: identity, network, pins, geometry, gains — MCU codegen **and** Linux `rosie run` |
| `agent.yaml` | Bridged robots: identity + bus + ROS topic map (`rosie agent`) |
| **Python** `Session` **/** `MobileRobot` | Host apps and scripts on the same bus |
| **Firmware library** | Linked into MCU projects by `rosie mcu setup` |

### Paths for a robot

**Native MCU** (Rosie owns hardware):

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot   # robot.yaml + thin DiffDriveStack main.cpp
# edit robot.yaml — pins, Wi‑Fi, geometry
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
```

**Native Linux** (Pi / Jetson, Rosie owns hardware):

```bash
# on the robot — robot.yaml with platform: linux
pip install "rosie-framework[linux]"
rosie run --config robot.yaml
# laptop: rosie teleop / viz / fleet list — same as MCU
```

**Bridge** (ROS / commercial stack owns hardware):

```bash
# on the robot (ROS already running)
pip install rosie-framework
rosie agent init --robot turtle1 --fleet lab --connect tcp/<router>:7447
rosie agent run
# laptop: same teleop / viz / fleet tools — no ROS on the laptop
```

See [Mobile base](docs/mobile-base.md), [BYOR](docs/byor.md), and
[Bridges](docs/bridges.md).

### Host only

```bash
python examples/minimal-pub-sub/talker.py
# another terminal
python examples/minimal-pub-sub/listener.py
```

### Useful CLI

| Command | What it does |
| ------- | ------------ |
| `rosie teleop --robot mybot` | WASD keyboard teleop → `cmd_vel` |
| `rosie drive --config robot.yaml` | Interactive REPL (goto, teleop, camera) for native MobileBase |
| `rosie tune --config robot.yaml` | Live-tune onboard velocity PID; `save` writes gains back to YAML |
| `rosie fleet list --fleet <id>` | Discover robots from presence heartbeats |
| `rosie topic list --fleet <id>` | List live topics under a fleet |
| `rosie bag …` | Record / play / info fleet bags; export to MCAP |
| `rosie viz --fleet <id>` | Browser 2D fleet viewer (poses / trails) |
| `rosie run --config robot.yaml` | Linux-native mobile base (`platform: linux`) |
| `rosie agent init` / `run` | ROS 2 ↔ Rosie bridge on the robot |
| `rosie mcu build` / `flash` / `monitor` | Compile, flash, and serial-monitor an MCU project |
| `rosie drivers list` | Print supported / planned driver and base inventory |

Fleet networking (dedicated AP vs SoftAP): [docs/fleet-networking.md](docs/fleet-networking.md).
Fleet management (init / add / router): [docs/fleet-management.md](docs/fleet-management.md).
Security (solo/fleet × open/secure): [docs/security.md](docs/security.md).

## Docs

- [Motivation](docs/motivation.md) — goals, Rosie vs ROS 2, native vs bridge
- [Getting started](docs/getting-started.md)
- [Robots: native vs bridge](docs/bridges.md) — when to use `rosie run` vs `rosie agent`
- [Bring Your Own Robot](docs/byor.md) — stand up a new native robot
- [Mobile base](docs/mobile-base.md) — `robot.yaml`, DiffDriveStack, Linux `rosie run`
- [Drivers](docs/drivers.md) — inventory (`rosie drivers list`)
- [Architecture](docs/architecture.md)
- [Fleet networking](docs/fleet-networking.md)
- [Fleet management](docs/fleet-management.md) — membership, SoftAP vs shared Wi‑Fi vs fleet
- [Security](docs/security.md) — four modes (open/secure), allowlist, ESP32 limits
- [Conventions](docs/conventions.md) — topics, robot/fleet identity, fleet robot contract
- [Messages & codegen](docs/messages.md)
- [Writing sessions (Python)](docs/writing-sessions.md)
- [Viz](docs/viz.md) — browser 2D fleet / bag viewer
- [Firmware](docs/firmware.md) — library details / advanced escape hatches

## Layout

```
rosie/
  python/          # pip package `rosie` + CLI (run, agent, tools, …)
  firmware/        # MCU library (Session, DiffDriveStack, drivers) — linked via `rosie mcu setup`
  interfaces/      # std_msgs.yaml + gen.py
  assets/          # brand mark (Rosie the Riveter–inspired icon)
  docs/
  examples/        # minimal talker/listener + sample fleet manifest
  tools/           # sample zenohd config (also packaged in the wheel)
```
