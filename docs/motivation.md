# Motivation

## Purpose

Rosie aims to be **modular and powerful like ROS 2**, while optimizing for goals
where the existing alternatives (ROS2) fall short:

1. **Simplicity to install** — minutes to a working bus on a laptop.
2. **Simplicity to work with** — small mental model, one robot description file,
   batteries-included mobile base for MCU cars.
3. **First-class support for heterogeneous robot fleets** — robot and fleet as
   real identity, MCU and Linux robots on the same brokered bus.

Rosie is intended to be easy to get started with for teaching and research in
robotics, but also powerful and extensible enough to use on real-world
professional robotics projects.

## Why choose Rosie

### 1. Simplicity to install

1. **Install in minutes, not hours.**  
   `pip install rosie` (optional `[mcu]`) on macOS, Linux, or Windows. No
   distro pin, no robostack rabbit hole, no DDS/RMW wrestling before you can
   publish a twist.

2. **Works cleanly on a laptop.**  
   Host tooling is Zenoh + Python. Join a shared Wi‑Fi (dedicated travel
   router for fleets, or SoftAP for a single robot) → `rosie router` → teleop.
   Teaching labs and desk demos do not need an Ubuntu robot PC.

### 2. Simplicity to work with

1. **One schema source for host and MCU.**  
   Edit `interfaces/std_msgs.yaml` once; codegen writes Python and C++. JSON
   on the wire stays readable for debugging; images stay raw bytes.

2. **One file describes the robot.**  
   A single `robot.yaml` (drivers, pins, geometry, gains, network) drives both
   firmware codegen and host defaults. No hand-authored URDF/xacro **plus** a
   separate `ros2_control` YAML just to drive a base — pick drivers from the
   Rosie inventory and flash. (Sim/RViz-style URDF can be generated later from
   the same file if needed, rather than authored up front.)

3. **Batteries-included mobile base (MCU-friendly).**  
   `robot.yaml` + `DiffDriveStack` (or raw `MobileBase`) + driver inventory give
   teleop / goto / deadman / optional onboard velocity PID without assembling a
   ros2_control stack. Steering variants plug in via kinematics; other vehicle
   classes would be sibling abstractions on Session.

4. **Simpler mental model.**  
   A **Session** is a process-local Zenoh handle bound to a robot. Sensors and
   commands are **topics under that robot**, not a separate graph node per
   driver. Less ceremony, same pub/sub habits.

5. **Right-sized stack.**  
   No QoS matrices, TF trees, or colcon workspace required to drive a car.
   You get router, doctor, teleop, drive, fleet, topic, bag, and flash in one
   CLI — enough for research bring-up without carrying the full robotics
   middleware.

### 3. First-class heterogeneous fleets

1. **MCU and fleets are native.**  
   ESP32 speaks Zenoh directly (`zenoh-pico`) as a client. Multi-robot fleets
   share a **dedicated AP** and one brokered router — not home Wi‑Fi and not
   one robot SoftAP per car. The firmware library and `rosie mcu flash` are part
   of the same package story as the host CLI. Heterogeneous types (MCU + Pi /
   Jetson) share one bus. See [Fleet networking](fleet-networking.md).

2. **Robot and fleet are real, not naming conventions.**  
   ROS 2’s graph is a flat soup of nodes/topics; multi-robot usually means
   `/robot1/...` prefixes and remapping. Rosie makes **robot** (and optional
   **fleet**) first-class identity: topic paths are structural, presence is
   discoverable, and fleet helpers cover list / wait / estop / leader stubs.

3. **Discovery that scales.**  
   Zenoh clients talk through `rosie router` instead of DDS-style multicast
   peer discovery. Visibility is scoped by fleet/robot topic paths and
   presence, not “everything sees everything.”

4. **Fleet-native tooling (not one machine’s graph).**  
   ROS 2’s `topic list` / RViz / rosbag mostly assume a single coherent
   graph; introspecting or recording a multi-robot team is clumsy. Rosie keys
   are `{fleet}/{robot}/…`, and the brokered router sees the whole bus from
   one laptop. CLI defaults to **fleet as the unit of view**: `rosie fleet
   list`, `rosie topic list` (grouped by robot), `rosie topic echo --key
   '*/pose'`, and `rosie bag record/play` from the router vantage.

5. **Team bring-up, not N× robot launch.**  
   ROS 2 launch and parameters compose poorly into “bring up the whole team.”
   Rosie uses a **fleet manifest** as the composition root (`rosie fleet wait
   --manifest …` / `Fleet.wait`): expected robots, optional required presence
   status, shared defaults / per-robot overlays for apps to read. MCU robots
   keep flash/env identity; fleet signals stay on `{fleet}/_fleet/…`.

## Side-by-side (Rosie vs ROS 2)

| Dimension | ROS 2 | Rosie |
|-----------|-------|-------|
| Install | Distro / apt / robostack; heavy tooling | `pip install rosie` (+ optional `[mcu]`) |
| macOS / Windows host | Possible but painful (DDS, RMW) | First-class: Zenoh + Python |
| Transport | DDS via RMW | Zenoh (`rosie router` / zenohd) |
| Discovery | Flat multicast peer discovery (scales poorly) | Brokered clients → router; presence for membership |
| Wire format | CDR / IDL | JSON (+ raw bytes for images) |
| Messages | `.msg` / `.idl` per package | Single `std_msgs.yaml` → Python + C++ |
| Robot description | URDF/xacro + often `ros2_control` YAML | Single `robot.yaml` → firmware + host |
| Mobile base | Assemble controllers / hw interfaces | Opt-in `DiffDriveStack` / `MobileBase` + config-first velocity PID (`rosie tune`) |
| Graph identity | Flat nodes/topics; namespaces by convention | **Robot** (+ optional **Fleet**) first-class |
| Multi-robot | Namespaces + remapping; no fleet primitives | Dedicated AP + presence + `Fleet` helper + fleet topics |
| Tooling scope | One machine / one flat graph; fleet view is awkward | `topic list` / `echo` / `bag` scoped by fleet from the router |
| Launch / config | Per-robot launch + remapping; weak team composition | Fleet manifest + `fleet wait`; overlays, not remaps |
| MCU | Not native; bridge stacks | ESP32 zenoh-pico client (station on fleet AP; SoftAP solo fallback) |
| Process model | Node ≈ graph participant (often per driver) | **Session** = process handle; topics under a robot |
| QoS / TF / actions | Full stack | Intentionally omitted or phased roadmap |
| Bags | Mature `rosbag2` | Lightweight fleet JSONL `.rosiebag` (router-host record/play) |
| Teaching / research bring-up | Hours–days for a clean install | Shared AP + `rosie router` + teleop in minutes |

## What we keep from ROS 2

- Processes that **publish and subscribe**
- **Topics** with structured keys under a robot (+ optional fleet)
- **Shared message contracts** across languages
- Relative vs absolute topic names
- Fleet-scoped **introspection** and **bags**; room for **actions** (roadmap)
- A small CLI for router, doctor, teleop, drive, fleet, topic, bag, and `rosie mcu …`

## What we drop on purpose

- DDS and complex QoS matrices
- `rcl` / `rmw` layering and colcon/ament as hard requirements
- Custom IDL + CDR as the default wire format
- Treating every sensor as its own named graph node
- Parameter and lifecycle *servers* as required infrastructure
- Free-form namespaces as the only multi-robot story
- Hand-authored URDF as the bring-up description for robots

## What we do differently

| Problem | Rosie approach |
|---------|----------------|
| Message definitions drift between Python and C++ | Single `interfaces/std_msgs.yaml` → generate both |
| MCU + host on a shared demo network | Zenoh **clients** → `rosie router`; dedicated AP for fleets ([Fleet networking](fleet-networking.md)) |
| Opaque binary wires | JSON payloads (plus raw bytes for images) |
| Heavy install for a teaching robot | `pip install rosie[mcu]` + `rosie` CLI (bus + PlatformIO wrap) |
| Flat graph / bolted-on namespaces | First-class **robot** (+ optional **fleet**); Session is the process handle |
| Tooling assumes one machine’s graph | Fleet-scoped `topic list` / `echo` / `bag` from the brokered router |
| Launch doesn’t compose into “bring up the team” | Fleet manifest + `fleet wait`; per-robot overlays instead of remapping |
| Driving a car requires many packages | `robot.yaml` + `DiffDriveStack` + `rosie drive` |

## Host vs MCU

| Role | Examples | How Rosie is used |
|------|----------|-------------------|
| **Host / Linux robot** | laptop, Raspberry Pi, Jetson | `pip install rosie` → `rosie setup` + Python sessions / `Robot` / fleet / topic / bag |
| **MCU** | ESP32, (later RP2040 / STM32, …) | `pip install rosie[mcu]` → `rosie mcu init` / `setup` / `build` / `flash` |

Pi and Jetson are **not** under `rosie mcu` — they run the host stack on Linux.
PlatformIO is the MCU build/flash backend only. Hosts never need it.

## Framework vs application

Rosie owns **transport, session lifecycle, robot/fleet topic naming, message
schemas, DiffDriveStack / MobileBase / common chip drivers, `robot.yaml`
codegen, and the host CLI**. Robots supply **`robot.yaml` (pins, ids, gains), a
thin DiffDriveStack `main.cpp` (or BYO glue), and only exotic hardware** not in
the [driver inventory](drivers.md).

## When ROS 2 is still the better fit

Use ROS 2 when you need large existing stacks (Nav2, MoveIt, rich TF trees),
mature bag tooling, or must interoperate with a DDS-based fleet already in
production.

Use **Rosie** when install friction, ease of robot bring-up, laptop/macOS hosts, and
**first-class multi-robot fleets** matter more than the full ROS ecosystem.

Networking: [Fleet networking](fleet-networking.md). Architecture: [Architecture](architecture.md).
Mobile base: [Mobile base](mobile-base.md).
