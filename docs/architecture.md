# Architecture

```text
┌──────────────────┐       Zenoh        ┌──────────────┐
│  Host            │◄── zenohd :7447 ──►│  MCU / robot │
│  laptop / Pi /…  │    (JSON / bytes)  │  ESP32 / …   │
│  rosie.Session   │                    │  rosie::Session│
│  app sessions    │                    │  app firmware│
└──────────────────┘                    └──────────────┘
         ▲                                       ▲
         │         shared Wi‑Fi (stations)       │
         └──────────────┬────────────────────────┘
                        │
               ┌────────┴────────┐
               │  Dedicated AP   │
               │  (travel router)│
               └─────────────────┘
```

Hosts run the Python package and `rosie router`. MCUs run the Rosie firmware
library (built/flashed via PlatformIO / `rosie mcu flash`). Networking details:
[Fleet networking](fleet-networking.md).

## Fleet topology (recommended)

Multi-robot and heterogeneous fleets use a **dedicated access point** (pocket /
travel router) that you control — not home Wi‑Fi and not a robot’s SoftAP.

1. Power the dedicated AP (fixed SSID / password for the fleet).
2. Laptop and all robots join that SSID as **stations**.
3. Host runs `rosie router` (zenohd) listening on `tcp/0.0.0.0:7447`.
4. Every robot opens a Zenoh **client** to `tcp/<host-ip>:7447`
   (`ROSIE_CONNECT` on hosts).

Discovery is brokered through the router. Application membership uses
`presence` and `rosie fleet list`. See [Fleet networking](fleet-networking.md).

## Solo SoftAP fallback (one robot)

For a single MCU with no travel router:

1. Robot starts Wi‑Fi SoftAP (`rosie::softAP` — ESP32 helper, optional).
2. Host joins that AP (often gets `192.168.4.2`).
3. Host runs `rosie router`.
4. Robot opens a Zenoh **client** to `tcp/192.168.4.2:7447`.

This is **one robot ↔ one host** only. A laptop cannot join multiple robot
SoftAPs at once — SoftAP is not the fleet path.

## Identity model

| Entity | Role |
|--------|------|
| **Fleet** (optional) | Shared scope, membership, fleet-wide topics |
| **Robot** | Identity + topic boundary |
| **Session** | Process-local Zenoh handle (pub/sub/timers) |
| **Topic** | I/O surface under a robot (or under `{fleet}/_fleet/`) |

## Sessions

- **Python (host):** `rosie.Session` — connect, publish/subscribe, params, timers, `spin()`.
- **Firmware (MCU):** `rosie::Session` — publishers/subscribers, `publishJson` with stamp, `poll()` / background read+lease tasks.

Application code never needs to call zenoh-pico / eclipse-zenoh APIs directly.
One Session per process is typical; many topics live under the same robot.

## CLI

The `rosie` console script wraps the bus. Host/Linux robots (laptop, Pi, Jetson)
use top-level commands; MCU boards use `rosie mcu …` (requires `[mcu]` /
PlatformIO):

| Command | Role |
|---------|------|
| `rosie setup` | Fetch/cache `zenohd` while online |
| `rosie router` | Run the Zenoh router |
| `rosie doctor` | Check install / connectivity |
| `rosie teleop` | WASD → `<robot>/cmd_vel` |
| `rosie fleet …` | List / wait / topics / estop / leader |
| `rosie topic …` | Fleet-scoped list / echo (grouped by robot) |
| `rosie bag …` | Record / play fleet traffic (`.rosiebag`) |
| `rosie mcu …` | MCU / PlatformIO: `setup` / `link` / `build` / `flash` / `monitor` |

## Messages

JSON objects usually include a top-level stamp:

```json
{ "stamp": 123.4, "v": 0.2, "w": 0.0 }
```

- Host `stamp` is wall-clock seconds.
- MCU `stamp` is `millis()/1000.0` (monotonic) — documented, not wall clock.
- Plain dicts are first-class; typed `std_msgs` classes are optional.

Raw topics (e.g. JPEG) skip JSON and publish bytes.

Topic naming and identity: [Conventions](conventions.md). Message catalog: [Messages](messages.md).

Firmware sessions are capped at 8 publishers / 8 subscribers and a small JSON
publish buffer — see [Firmware](firmware.md).

## Framework vs robot

| Rosie | Your robot |
|-------|------------|
| Session, pub/sub, SoftAP + **wifiStation** | `robot.yaml` pins, ids, credentials, gains |
| `DiffDriveStack` / `MobileBase`, common drivers | Thin `main.cpp` (or BYO wiring for exotic HW) |
| Cascaded goto + optional velocity PID (`rosie tune`) | Custom `VelocityController` / `cmd` ops |
| Robot / fleet identity, manifest wait, topic/bag/`drive` CLI | Choosing ids, manifest contents, mission readiness beyond presence |

Standing up a new robot: [BYOR](byor.md). Mobile base: [Mobile base](mobile-base.md).
Drivers: [Drivers](drivers.md). Networking: [Fleet networking](fleet-networking.md).
Why not ROS 2: [Motivation](motivation.md).
