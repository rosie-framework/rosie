# Docs

## Start here

- [Getting started](getting-started.md)
- [Motivation](motivation.md)
- [Architecture](architecture.md)
- [Conventions](conventions.md) — topics, identity, fleet robot contract
- [Messages](messages.md)

## Robots

- [Bring Your Own Robot](robots/byor.md) — native MCU / Linux bring-up
- [Robots: native vs bridge](robots/bridges.md) — `rosie run` vs `rosie agent`
- [Mobile base](robots/mobile-base.md) — `robot.yaml`, DiffDriveStack, Linux `rosie run`, topics
- [Drivers](robots/drivers.md) — inventory (`rosie drivers list`)
- [Firmware](robots/firmware.md) — MCU library / advanced Session

## Host (laptop)

- [Writing sessions](host/writing-sessions.md) — Python `Session`
- [MobileRobot](host/mobile-robot.md) — host MobileBase client API
- [Fleet](host/fleet.md) — host fleet discovery / wait / estop API
- [Viz](host/viz.md) — `rosie viz` browser map / bag scrub

## Fleet

- [Networking](fleet/networking.md) — dedicated AP vs SoftAP
- [Management](fleet/management.md) — init / add / router
- [Security](fleet/security.md) — open vs secure, allowlist
