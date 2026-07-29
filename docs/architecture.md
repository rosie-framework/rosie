# Architecture

Rosie is a **brokered fleet bus**: processes join a shared Zenoh router
(`rosie router` / zenohd) and exchange JSON or raw bytes on named topics.
Hosts run the Python package; MCUs run the Rosie firmware library
(`rosie mcu flash`). Why this shape: [Motivation](motivation.md).

```text
              shared Wi‑Fi (everyone is a station*)
┌─────────────────────────────────────────────────────┐
│                                                     │
│   ┌────────────────┐    Zenoh     ┌──────────────┐  │
│   │ Host           │◄────────────►│ Robot(s)     │  │
│   │ laptop / Pi /… │  JSON/bytes  │ ESP32 / …    │  │
│   │                │              │              │  │
│   │ rosie router   │   :7447      │ Session      │  │
│   │ + app Sessions │              │ (firmware /  │  │
│   │                │              │  rosie run)  │  │
│   └────────▲───────┘              └──────▲───────┘  │
│            │                             │          │
│            └──────────────┬──────────────┘          │
│                           │                         │
│                  ┌────────┴────────┐                │
│                  │    Wi‑Fi AP     │                │
│                  │ dedicated AP,   │                │
│                  │ laptop AP, or   │                │
│                  │ robot SoftAP*   │                │
│                  └─────────────────┘                │
└─────────────────────────────────────────────────────┘
```

\* **Fleet path:** a dedicated AP (or laptop AP); all robots join as stations.
\* **Solo fallback:** one robot runs SoftAP and the host joins it — not for
multi-robot fleets. Details below and in [Fleet networking](fleet/networking.md).

## Bus, Session, Topic

Three layers to keep straight:

| Layer | What it is | Example |
|-------|------------|---------|
| **Bus** | Shared Zenoh network: router + everyone connected to it | `rosie router` on the laptop LAN |
| **Session** | One **process’s** connection to the bus, bound to a robot id (+ optional fleet) | Firmware on `car1`; `rosie teleop` on the laptop |
| **Topic** | One named I/O channel under that identity | `pose`, `cmd_vel`, `imu` |

- The **bus** is infrastructure. It routes keys and payloads; it does not know
  about sensors or apps.
- A **Session** is the client handle (`rosie.Session` / `rosie::Session`). It
  owns that process’s publishers and subscribers. Typical: **one Session per
  process**, not one per sensor.
- A **Topic** is an I/O surface. Relative names (`pose`) resolve under the
  Session’s identity to wire keys such as `lab/car1/pose`. Many topics share
  one Session.

```text
bus (zenohd)
 ├── Session: car firmware   (robot=car1, fleet=lab)
 │     pubs: pose, presence, encoders?, imu?, …
 │     subs: cmd_vel, goto, cmd
 └── Session: laptop teleop  (robot=car1, fleet=lab)
       pubs: cmd_vel
       subs: (optional) pose
```

Same robot id / topic namespace, **different Sessions**. The car publishes
`pose`; the laptop publishes `cmd_vel`. The bus delivers between them.

On the **robot process**, one Session carries all onboard pubs and subs
(sensors, pose, commands). On the **host**, each tool (`teleop`, `drive`,
`viz`, a custom script) opens its **own** Session, usually bound to the same
robot id so relative names resolve into that robot’s namespace.

Topic naming, delivery classes, and the fleet robot contract:
[Conventions](conventions.md) ([Delivery and validity](conventions.md#delivery-and-validity)).
Python API: [Writing sessions](host/writing-sessions.md). MCU API / limits:
[Firmware](robots/firmware.md).

## Identity

| Entity | Role |
|--------|------|
| **Fleet** (optional) | Shared scope for multi-robot work; fleet-wide keys under `{fleet}/_fleet/…` |
| **Robot** | Required id; topic boundary for that machine (`{fleet}/{robot}/…` or `{robot}/…`) |
| **Session** | Process-local Zenoh handle bound to a robot (+ fleet) |
| **Topic** | Named channel (`pose`, `cmd_vel`, …) — not one Session per sensor |

## Networking (where the bus lives)

### Fleet topology (recommended)

Multi-robot fleets use a **Wi‑Fi AP you control** — typically a dedicated AP,
or optionally the laptop as AP. Prefer that over home / venue Wi‑Fi. Do **not**
use a robot SoftAP for fleets (see solo fallback below).

1. Bring up the AP (fixed SSID / password).
2. Laptop and all robots join that SSID as **stations**.
3. Host runs `rosie router` listening on `tcp/0.0.0.0:7447`.
4. Every **MCU** opens a Zenoh **client** to `tcp/<host-lan-ip>:7447`
   (`robot.yaml` `network.connect`). Host tools on the router machine default
   to `tcp/127.0.0.1:7447` (override with `ROSIE_CONNECT` if remote).

Discovery is brokered through the router. Application membership uses
`presence` and `rosie fleet list`. Details: [Fleet networking](fleet/networking.md).

### Solo SoftAP fallback (one robot)

For a single MCU with no shared AP:

1. Robot starts Wi‑Fi SoftAP (`rosie::softAP`).
2. Host joins that AP (often `192.168.4.2`).
3. Host runs `rosie router`.
4. Robot opens a Zenoh client to `tcp/192.168.4.2:7447`.

**One robot ↔ one host only.** SoftAP is not the fleet path.

## Messages

Structured topics are UTF-8 JSON, usually with a top-level `stamp`:

```json
{ "stamp": 123.4, "v": 0.2, "w": 0.0 }
```

- Host `stamp`: wall-clock seconds.
- MCU `stamp`: `millis()/1000.0` (monotonic — not wall clock).
- Plain dicts are first-class; typed `std_msgs` classes are optional.
- Large blobs (e.g. JPEG) use raw bytes, not JSON.

Catalog: [Messages](messages.md). MCU publisher / JSON buffer caps:
[Firmware](robots/firmware.md).

## Framework vs robot

| Rosie provides | You provide |
|----------------|-------------|
| Session, pub/sub, SoftAP + **wifiStation** | `robot.yaml` pins, ids, credentials, gains |
| `DiffDriveStack` / `MobileBase`, inventory drivers | Thin `main.cpp`; choose drivers in YAML (or BYO / raw `MobileBase`) |
| Goto + optional velocity PID (`rosie tune`) | Custom `VelocityController` / `cmd` ops when needed |
| Fleet identity, manifest wait, topic / bag / drive CLI | Robot ids, manifest roster, mission logic beyond presence |

## Tooling map

The `rosie` CLI talks to the same bus. Host / Linux robots use top-level
commands; MCU boards use `rosie mcu …`. Common entry points:

| Area | Commands |
|------|----------|
| Bus | `setup`, `router`, `doctor` |
| Drive / inspect | `teleop`, `drive`, `topic`, `viz`, `bag` |
| Fleet | `fleet …`, `secret apply` |
| Robot backends | `mcu …`, `run`, `agent …` |

Install and first bring-up: [Getting started](getting-started.md).
Standing up a robot: [BYOR](robots/byor.md). Mobile stack:
[Mobile base](robots/mobile-base.md). Drivers: [Drivers](robots/drivers.md).
Fleet ops: [Management](fleet/management.md).
