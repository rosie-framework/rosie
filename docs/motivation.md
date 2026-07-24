# Motivation

Rosie is the easy **fleet layer** for mixed robots — MCU, Linux, and ROS —
from a normal laptop. It aims to be easy to get started with for teaching and
research, and extensible enough for real projects — while optimizing for goals
where heavier stacks (notably ROS 2 as a full on-robot + laptop install) are a
poor fit for **multi-robot teams**.

## Goals

1. **Robot fleets are first-class** — robot and fleet as real identity;
   discover, coordinate, and introspect a heterogeneous team from one laptop.
   This is why Rosie exists.
2. **Easy to get started** — low learning curve: minutes to a working bus,
   one robot description, a small mental model and CLI.
3. **One fleet across backends** — MCU, Linux robots, and host laptops
   (macOS, Linux, Windows), as a **native** stack or as a **bridge** over
   another backend (e.g. ROS 2). Membership and tooling span those paths;
   Rosie does not require rewriting every robot.

## 1. Robot fleets are first-class

Most frameworks treat multi-robot as topic prefixes and launch files. Rosie
makes the **team** the default unit of work.

1. **Robot and fleet are real, not naming conventions.**  
   ROS 2’s graph is a flat soup of nodes/topics; multi-robot usually means
   `/robot1/...` prefixes and remapping. Rosie makes **robot** (and optional
   **fleet**) first-class identity: topic paths are structural, presence is
   discoverable, and fleet helpers cover list / wait / estop / leader stubs.

2. **Heterogeneous teams on one bus.**  
   MCU (zenoh-pico), Linux native (`rosie run`), and bridged ROS robots
   (`rosie agent`) share a **dedicated AP** and one brokered `rosie router`.
   Not home Wi‑Fi chaos and not one SoftAP per car for fleets. See
   [Fleet networking](fleet-networking.md).

3. **Discovery that scales.**  
   Zenoh clients talk through `rosie router` instead of DDS-style multicast
   peer discovery. Visibility is scoped by fleet/robot topic paths and
   presence, not “everything sees everything.”

4. **Fleet-native tooling (not one machine’s graph).**  
   ROS 2’s `topic list` / RViz / rosbag mostly assume a single coherent graph;
   introspecting or recording a multi-robot team is clumsy. Rosie keys are
   `{fleet}/{robot}/…`, and the brokered router sees the whole bus from one
   laptop: `rosie fleet list`, `rosie topic list`, `rosie viz --fleet`,
   `rosie bag record/play`.

5. **Team bring-up, not N× robot launch.**  
   A **fleet manifest** is the composition root (`rosie fleet wait --manifest
   …` / `Fleet.wait`): expected robots, optional presence status, shared
   defaults / per-robot overlays. Native robots keep flash/env or `robot.yaml`
   identity; bridged robots keep `agent.yaml`. Fleet signals live under
   `{fleet}/_fleet/…`.

Either way, a robot is just an id under `{fleet}/{robot}/…` honoring the
[fleet robot contract](conventions.md#fleet-robot-contract). Laptop tools do
not care whether a given robot is native or bridged.

## 2. Easy to get started

Fleets only matter if people can actually stand them up.

1. **Install in minutes.**  
   `pip install rosie-framework` (optional `[mcu]`, `[linux]`, `[camera]`) on macOS,
   Linux, or Windows. No distro pin, no robostack rabbit hole, no DDS/RMW
   wrestling before you can publish a twist or list a fleet.

2. **Works cleanly on a laptop.**  
   Host tooling is Zenoh + Python. Join a shared Wi‑Fi (dedicated travel
   router for fleets, or SoftAP for a single MCU) → `rosie router` → teleop /
   viz. Teaching labs and desk demos do not need an Ubuntu robot PC for the
   laptop.

3. **One schema source for host and MCU.**  
   Edit `interfaces/std_msgs.yaml` once; codegen writes Python and C++. JSON
   on the wire stays readable for debugging; images stay raw bytes.

4. **One file describes a native robot.**  
   A single `robot.yaml` (drivers, pins, geometry, gains, network) drives MCU
   firmware codegen **and** Linux `rosie run`. Shared sections port across
   platforms; only motor/encoder/IMU blocks are platform-specific. Bridged
   robots use a smaller `agent.yaml` (identity + bus + ROS topic map) — no
   pins, because ROS owns hardware.

5. **Batteries-included mobile base.**  
   Native: `DiffDriveStack` / `MobileBase` (MCU) or `rosie run` (Linux) give
   teleop / goto / deadman / common chip drivers without assembling
   `ros2_control`. Bridged: reuse the robot’s existing stack; agent maps
   `cmd_vel` / odom / presence into the fleet contract.

6. **Simpler mental model.**  
   A **Session** is a process-local Zenoh handle bound to a robot. Sensors and
   commands are **topics under that robot**, not a separate graph node per
   driver. One CLI covers router, doctor, teleop, drive, run, agent, fleet,
   topic, bag, viz, and MCU flash — enough for research bring-up without the
   full robotics middleware.

## 3. One fleet across backends

Rosie is not pinned to one OS, one board class, or one way of owning hardware.
The point is **one fleet model** — membership and laptop tooling — across
native and bridged robots, not “rewrite every robot in Rosie.”

| Where | Role |
|-------|------|
| **Laptop (macOS / Linux / Windows)** | Fleet tooling only: `rosie router`, teleop, viz, bag, `Session` / `MobileRobot`. No ROS or DDS required on the host. |
| **MCU (ESP32, …)** | **Native**: Rosie firmware from `robot.yaml` (`rosie mcu …`). Zenoh client on the robot. |
| **Linux robot (Pi, Jetson, DIY)** | **Native**: same `robot.yaml` shape with `platform: linux` → `rosie run`. Or **bridge**: keep ROS (etc.) and run `rosie agent`. |
| **Commercial / ROS robot** | **Bridge**: `agent.yaml` + `rosie agent` — ROS owns drivers/autonomy; Rosie owns fleet membership and laptop tooling. |

| Path | Examples | How Rosie is used |
|------|----------|-------------------|
| **Native MCU** | ESP32 car | `robot.yaml` → `rosie mcu init` / `setup` / `flash` |
| **Native Linux** | Raspberry Pi, Jetson DIY | `robot.yaml` (`platform: linux`) → `rosie run` |
| **Bridge** | TurtleBot, commercial ROS robots | `agent.yaml` → `rosie agent init` / `run` |

**Go native** when Rosie would be the robot's first real software stack (MCU,
DIY Linux). **Bridge** when the robot already has a stack worth keeping
(commercial / ROS). Decision table: [Robots: native vs bridge](bridges.md).

ESP32 is not “MCU-only Rosie,” and Pi is not “must use ROS.” Native Linux is
Python on the robot (`rosie run`); PlatformIO/`rosie mcu` is MCU-only. Hosts
never need firmware tooling.

## Side-by-side (Rosie vs ROS 2)

| Dimension | ROS 2 | Rosie |
|-----------|-------|-------|
| Focus | General robotics middleware | Lightweight **fleet** layer + optional native stack |
| Install (host) | Distro / apt / robostack; heavy tooling | `pip install rosie-framework` (+ optional extras) |
| macOS / Windows host | Possible but painful (DDS, RMW) | First-class: Zenoh + Python |
| Transport | DDS via RMW | Zenoh (`rosie router` / zenohd) |
| Discovery | Flat multicast peer discovery | Brokered clients → router; presence for membership |
| Wire format | CDR / IDL | JSON (+ raw bytes for images) |
| Messages | `.msg` / `.idl` per package | Single `std_msgs.yaml` → Python + C++ |
| Native robot description | URDF/xacro + often `ros2_control` | Single `robot.yaml` → MCU firmware **or** `rosie run` |
| Bridged robot | N/A (ROS *is* the stack) | `agent.yaml` + `rosie agent` (ROS keeps drivers) |
| Mobile base | Assemble controllers / hw interfaces | Native: DiffDriveStack / `rosie run`; or bridge existing stack |
| Graph identity | Flat nodes/topics; namespaces by convention | **Robot** (+ optional **Fleet**) first-class |
| Multi-robot | Namespaces + remapping; no fleet primitives | Dedicated AP + presence + `Fleet` + fleet topics |
| Tooling scope | One machine / one flat graph | Fleet-scoped `topic` / `viz` / `bag` from the router |
| MCU | Not native; micro-ROS / bridges | ESP32 zenoh-pico client (native firmware) |
| Linux robot | Typical ROS 2 install | Native `rosie run` **or** ROS + `rosie agent` |
| Process model | Node ≈ graph participant | **Session** = process handle; topics under a robot |
| QoS / TF / ROS actions | Full stack | Omitted; goals use `goto` + `nav_result` topics |
| Bags | Mature `rosbag2` | Fleet JSONL `.rosiebag` (+ gzip, MCAP export) |
| Teaching / research bring-up | Hours–days for a clean install | Shared AP + `rosie router` + teleop in minutes |

## What we keep from ROS 2

- Processes that **publish and subscribe**
- **Topics** with structured keys under a robot (+ optional fleet)
- **Shared message contracts** across languages
- Relative vs absolute topic names
- Fleet-scoped **introspection** and **bags**; navigation goals via ordinary
  topics (`goto` / `nav_result`), not a separate Action type
- A small CLI for router, doctor, teleop, drive, run, agent, fleet, topic, bag,
  viz, and `rosie mcu …`

## What we drop on purpose

- DDS and complex QoS matrices (on the Rosie bus)
- `rcl` / `rmw` layering and colcon/ament as hard requirements for Rosie itself
- Custom IDL + CDR as the default wire format
- Treating every sensor as its own named graph node
- Parameter and lifecycle *servers* as required infrastructure
- Free-form namespaces as the only multi-robot story
- Hand-authored URDF as the bring-up description for **native** robots

## What we do differently

| Problem | Rosie approach |
|---------|----------------|
| Flat graph / bolted-on namespaces | First-class **robot** (+ optional **fleet**); Session is the process handle |
| Tooling assumes one machine’s graph | Fleet-scoped `topic list` / `echo` / `bag` / `viz` from the router |
| Launch doesn’t compose into “bring up the team” | Fleet manifest + `fleet wait`; overlays, not remaps |
| Commercial robot already has ROS | Keep it; `rosie agent` joins the Rosie fleet |
| MCU + host + Linux robots on a shared demo network | Zenoh **clients** → `rosie router`; dedicated AP for fleets |
| Message definitions drift between Python and C++ | Single `interfaces/std_msgs.yaml` → generate both |
| Opaque binary wires | JSON payloads (plus raw bytes for images) |
| Heavy install for a teaching fleet | `pip install rosie-framework` + optional `[mcu]` / `[linux]` |
| Driving a native car requires many packages | `robot.yaml` + DiffDriveStack or `rosie run` |

## Framework vs application

Rosie owns **transport, session lifecycle, robot/fleet topic naming, message
schemas, native mobile-base stack** (MCU DiffDriveStack / Linux `rosie run` +
drivers), **`robot.yaml` / `agent.yaml`**, **bridge agent**, and the **host
CLI**. Robots supply identity and config (`robot.yaml` or `agent.yaml`), a thin
native entrypoint (firmware `main.cpp` or nothing beyond `rosie run` / `rosie
agent`), and only exotic hardware not in the [driver inventory](drivers.md).

## When ROS 2 is still the better fit (on the robot)

Use **ROS 2 on the robot** when you need large existing stacks (Nav2, MoveIt,
rich TF trees), mature on-robot bag ecosystems, or must stay in a DDS-based
production stack — and join Rosie with **`rosie agent`** so the laptop and
fleet layer stay lightweight.

Use **Rosie natively** when install friction, simple bring-up, and a single
coherent stack on MCU or DIY Linux matter more than the full ROS ecosystem.

These are not exclusive: mixed fleets are the design point. Rosie always owns
fleet coordination and laptop tooling; the robot may be native or bridged.
Details: [Robots: native vs bridge](bridges.md).

Networking: [Fleet networking](fleet-networking.md). Architecture:
[Architecture](architecture.md). Mobile base: [Mobile base](mobile-base.md).
Getting started: [Getting started](getting-started.md).
