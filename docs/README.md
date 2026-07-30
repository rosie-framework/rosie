# Docs

## Start here

- [Getting started](getting-started.md)
- [Motivation](motivation.md) — differentiators; vs ROS 2 / Open-RMF / FreeFleet
- [Architecture](architecture.md) — bus / Session / Topic; topology; framework vs robot
- [Conventions](conventions.md) — topics, identity, fleet robot contract
- [Messages](messages.md)

## Robots

- [Bring Your Own Robot](robots/byor.md) — native MCU / Linux bring-up
- [Robots: native vs bridge](robots/bridges.md) — `rosie run` vs `rosie agent`
- [Mobile base](robots/mobile-base.md) — shared contract, DiffDrive / `rosie run` topics
- [Drivers](robots/drivers.md) — inventory (`rosie drivers list`)
- [Camera](robots/camera.md) — JPEG frames on `camera/compressed`, frame rate, host viewers
- [Firmware](robots/firmware.md) — MCU DiffDriveStack / PlatformIO / advanced Session
- [Linux run](robots/linux-run.md) — `rosie run`, Pi drivers, dry-run

## Host (laptop)

- [Writing sessions](host/writing-sessions.md) — Python `Session`
- [MobileRobot](host/mobile-robot.md) — host MobileBase client API
- [Fleet](host/fleet.md) — host fleet discovery / wait / estop API
- [Viz](host/viz.md) — `rosie viz` browser map / bag scrub

## Fleet

- [Networking](fleet/networking.md) — dedicated AP vs SoftAP
- [Management](fleet/management.md) — init / add / router
- [Security](fleet/security.md) — open vs secure, allowlist
