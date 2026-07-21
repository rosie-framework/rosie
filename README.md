# Rosie

Rosie is a modern, lightweight robotics framework, with an emphasis on multi-robot 
interaction. Rosie is easy to get started, yet powerful and extensible for 
professional applications.

## What Rosie provides

Rosie gives you a **full bring-up stack** — bus, robot description, MCU firmware
helpers, and host CLI — without needing a full ROS 2 install to drive a car or
stand up a small fleet.

- **Minutes to a working bus on a laptop** — `pip install`, `rosie router`,
  teleop. No Ubuntu robot PC or DDS/RMW setup required just to drive a car.
- **One file describes the robot** — `robot.yaml` (pins, drivers, geometry,
  gains, network) drives firmware codegen and host defaults.
- **Batteries-included mobile base** — DiffDriveStack / MobileBase: teleop,
  goto, deadman, optional onboard velocity PID, common chip drivers. Thin
  `main.cpp`; you edit YAML, not a control stack.
- **One CLI for the workflow** — router, doctor, teleop, drive, tune, fleet,
  topic, bag, and MCU build/flash.
- **MCU and Linux on the same bus** — ESP32 speaks Zenoh directly alongside
  Pi / Jetson / laptop hosts; no separate MCU stack.
- **First-class heterogeneous fleets** — robot and optional fleet are real
  identity (not topic prefixes). Dedicated AP + one brokered router;
  discover, wait, estop, and inspect the team from the CLI.

Deeper comparison with ROS 2: [docs/motivation.md](docs/motivation.md).

## Install

```bash
pip install -e python              # host: Session, CLI, router
pip install -e "python[mcu]"       # + MCU build / flash (PlatformIO under the hood)
pip install -e "python[camera]"    # + OpenCV for host camera snap / live view
# or: pip install -e "python[mcu,camera]"

rosie setup      # fetch zenohd once (while online)
rosie router     # start the bus
rosie doctor     # sanity-check the host
```

Details: [docs/getting-started.md](docs/getting-started.md). Notices: [NOTICE](NOTICE).

## How you work with Rosie


| Piece                              | Role                                                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `rosie` **CLI**                    | Bus (`router`, `doctor`), robots (`teleop`, `drive`, `tune`), fleets, topics, bags, MCU flash         |
| `robot.yaml`                       | One file for identity, network, pins, geometry, gains — drives firmware codegen **and** host defaults |
| **Python** `Session` **/** `Robot` | Host apps and scripts on the same bus                                                                 |
| **Firmware library**               | Linked into your MCU project by `rosie mcu setup`                                                     |




### Ground MCU robot (typical path)

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot   # robot.yaml + thin DiffDriveStack main.cpp
# edit robot.yaml — pins, Wi‑Fi, geometry
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
# optional: rosie tune --config robot.yaml   # live velocity PID
```

You edit `robot.yaml`, not C++ pin macros. The sketch is usually
`DiffDriveStack::begin()` / `loop()` — see [Mobile base](docs/mobile-base.md)
and [BYOR](docs/byor.md).

### Host only

```bash
python examples/minimal-pub-sub/talker.py
# another terminal
python examples/minimal-pub-sub/listener.py
```



### Useful CLI


| Command                                 | What it does                                                     |
| --------------------------------------- | ---------------------------------------------------------------- |
| `rosie teleop --robot mybot`            | WASD keyboard teleop → `cmd_vel`                                 |
| `rosie drive --config robot.yaml`       | Waypoints, teleop, camera REPL for a MobileBase robot            |
| `rosie tune --config robot.yaml`        | Live-tune onboard velocity PID; `save` writes gains back to YAML |
| `rosie fleet list --fleet <id>`         | Discover robots from presence heartbeats                         |
| `rosie topic list --fleet <id>`         | List live topics under a fleet                                   |
| `rosie mcu build` / `flash` / `monitor` | Compile, flash, and serial-monitor the MCU project               |
| `rosie drivers list`                    | Print supported / planned driver and base inventory              |


Fleet networking (dedicated AP vs SoftAP): [docs/fleet-networking.md](docs/fleet-networking.md).

## Docs

- [Motivation](docs/motivation.md) — purpose, Rosie vs ROS 2
- [Getting started](docs/getting-started.md)
- [Bring Your Own Robot](docs/byor.md) — stand up a new robot
- [Mobile base](docs/mobile-base.md) — `robot.yaml`, DiffDriveStack, tuning
- [Drivers](docs/drivers.md) — inventory (`rosie drivers list`)
- [Architecture](docs/architecture.md)
- [Fleet networking](docs/fleet-networking.md)
- [Conventions](docs/conventions.md) — topics, robot/fleet identity, units
- [Messages & codegen](docs/messages.md)
- [Writing sessions (Python)](docs/writing-sessions.md)
- [Firmware](docs/firmware.md) — library details / advanced escape hatches



## Layout

```
rosie/
  python/          # pip package `rosie` + CLI
  firmware/        # MCU library (Session, DiffDriveStack, drivers) — linked via `rosie mcu setup`
  interfaces/      # std_msgs.yaml + gen.py
  docs/
  examples/        # minimal talker/listener + sample fleet manifest
  tools/           # sample zenohd config (also packaged in the wheel)
```

