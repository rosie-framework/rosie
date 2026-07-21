# Rosie framework

Lightweight ROS2-inspired middleware for robots that talk over Zenoh.

## Install

```bash
pip install -e python
# with MCU build/flash tooling:
pip install -e "python[mcu]"

rosie setup      # fetch zenohd (once, while online)
rosie router     # start the bus
rosie doctor     # sanity-check the host
```

See [docs/getting-started.md](docs/getting-started.md). Third-party notices: [NOTICE](NOTICE).

## Firmware (MCU)

Add the PlatformIO / Arduino library from [`firmware/`](firmware/) to your
project (see [docs/firmware.md](docs/firmware.md)). Ground robots typically use
`robot.yaml` + [DiffDriveStack](docs/mobile-base.md):

```bash
rosie mcu init --robot mybot   # scaffold yaml + thin main.cpp
# or: rosie mcu setup          # link + gen-config in an existing project
rosie mcu flash
rosie drive --config robot.yaml
```

## Docs

- [Motivation](docs/motivation.md) — purpose, why Rosie vs ROS 2
- [Architecture](docs/architecture.md)
- [Mobile base](docs/mobile-base.md) — YAML, DiffDriveStack, host `Robot`
- [Drivers](docs/drivers.md) — inventory (`rosie drivers list`)
- [Fleet networking](docs/fleet-networking.md) — dedicated AP, SoftAP fallback
- [Getting started](docs/getting-started.md)
- [Conventions](docs/conventions.md) — topics, robot/fleet identity, units
- [Messages & codegen](docs/messages.md)
- [Writing sessions (Python)](docs/writing-sessions.md)
- [Firmware](docs/firmware.md)
- [Bring Your Own Robot](docs/byor.md)

## Layout

```
rosie/
  python/          # pip package `rosie` (+ `rosie` CLI)
  firmware/        # PlatformIO library `rosie` (+ DiffDriveStack / MobileBase)
  interfaces/      # std_msgs.yaml + gen.py
  docs/
  examples/        # minimal talker/listener + sample fleet manifest
  tools/           # sample zenohd config (also packaged in the wheel)
```

Fleet tooling: `rosie fleet wait`, `rosie topic list|echo`, `rosie bag record|play`
— see [Fleet networking](docs/fleet-networking.md).

## Robots

Reference robots (for example an ESP32-S3 car) live in **separate** projects —
they depend on Rosie via `pip install -e /path/to/rosie/python` and a firmware
library path (`rosie mcu setup`), with config in **`robot.yaml`**. Fleets use a
dedicated AP; SoftAP is a solo-robot fallback —
[Fleet networking](docs/fleet-networking.md).

Hosts (laptop / Pi / Jetson) use the Python package; MCUs use the firmware
library. See [Bring Your Own Robot](docs/byor.md).
