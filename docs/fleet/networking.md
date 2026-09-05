# Fleet networking

First-class multi-robot support in Rosie assumes a **shared Wi‑Fi network** and a
**brokered Zenoh bus** (`rosie router` / zenohd). Every robot and host is a Zenoh
**client** that connects to that router. Discovery is not flat multicast DDS —
see also [Motivation](../motivation.md) (Rosie vs ROS 2).

## Recommended topology (fleets)

Use a **dedicated access point** you control — typically a pocket / travel
router (e.g. GL.iNet) with its own SSID. Do **not** put the fleet on home,
venue, or site Wi‑Fi if you want portable research and field deployments that
move between networks.

```text
                    ┌─────────────────┐
                    │  Dedicated AP   │
                    │  (travel router)│
                    └────────┬────────┘
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
    ┌────────────┐    ┌────────────┐    ┌────────────┐
    │  Laptop    │    │  Robot A   │    │  Robot B   │
    │  (station) │    │  (station) │    │  (station) │
    │ rosie      │    │ zenoh-pico │    │ Zenoh      │
    │ router     │    │ client     │    │ client     │
    └────────────┘    └────────────┘    └────────────┘
```

Bring-up:

1. Power the dedicated AP (fixed SSID / password you document for the fleet).
2. Join the laptop (and any Linux robots) to that SSID.
3. On the **router host** (laptop, or a Pi on the same LAN):
   `rosie fleet init --fleet <id>` (once), then `rosie router --fleet <id>`.
   It announces `{fleet}/_fleet/router` and prints LAN locators.
   Host tools on that machine default to `tcp/127.0.0.1:7447` — no
   `ROSIE_CONNECT` required for the common case.
4. Point robots at the router with `connect: auto` or an explicit
   `tcp/<router-host-ip>:7447` — see [How robots find the router](#how-robots-find-the-router).
   Only set `ROSIE_CONNECT` on hosts when the router is **not** on localhost.
5. Flash / boot robots as **Wi‑Fi stations** on that SSID (not as SoftAPs).
   Firmware: `network.mode: station` in `robot.yaml` (DiffDriveStack /
   `rosie::mcuConnect`) or `rosie::wifiStation(ssid, password)` for custom glue
   that skips the shared retry helper.
6. Check membership: `rosie fleet list --fleet <id>`.

This works for **heterogeneous** fleets: ESP32 MCUs and Pi/Jetson robots are
all clients on the same L2 network. Identity stays `(fleet, robot)`; capability
differences live in topics and presence, not in who owns the AP.

## One-robot SoftAP (still a fleet)

For a **single** MCU robot with no travel router, the robot may still run
`rosie::softAP`, the laptop joins that AP, and the MCU connects as a Zenoh
client to the laptop (often `tcp/192.168.4.2:7447`). Init the fleet first
(`rosie fleet init --fleet <id>`), then `rosie router --fleet <id>`. Topics
are still `{fleet}/{robot}/…`.

That pattern is **one robot ↔ one host**. Two SoftAP cars need a dedicated AP.

## Laptop as AP (optional)

If you have no travel router, the laptop can host the Wi‑Fi AP (macOS Internet
Sharing, Linux `hostapd`, or a USB Wi‑Fi dongle in AP mode). Robots join the
laptop SSID; `rosie router` still runs on the laptop. Prefer a dedicated
travel router when you can — laptop SoftAP behavior varies by OS.

## How robots find the router

Rosie stays **brokered**: sessions open in Zenoh **client** mode against one
`rosie router`. Scouting only locates that router; it never routes data.
A mismatched fleet announcement is rejected.

| Setting | MCU | Linux (`rosie agent` / `rosie run`) | Host tools |
|---------|-----|-------------------------------------|------------|
| `connect: auto` | Codegen bakes the router-host LAN IP at flash time | Runtime scout + `{fleet}/_fleet/router` check | Treated as unset → `ROSIE_CONNECT` then localhost |
| `tcp/<ip>:7447` (explicit) | Baked as written; no scout | Connect there; no scout | Same |
| omitted | SoftAP → `tcp/192.168.4.2:7447`. Station → same as `auto` | Same as `auto` | localhost |

Use **`auto`** for field and ad-hoc networks where the router-host address is
not stable. Use an **explicit locator** when multicast is blocked, when you
need a reproducible bag against a declared topology, or when a multi-homed
host would advertise the wrong interface.

`rosie doctor --scout` probes whether multicast scouting works on this LAN
before you depend on `auto`.

Scout failure modes: campus / venue Wi‑Fi and AP client isolation often block
multicast; scout packets use TTL 1 so they do not cross a subnet; Wi‑Fi
multicast is sent at the lowest basic rate; containers without host networking
break it; a multi-homed router host may advertise addresses the robot cannot
reach. In those cases set `tcp/<router-host-ip>:7447`.

## Discovery and visibility

| Concern | Rosie approach |
|---------|----------------|
| Middleware discovery | Brokered clients → one router. Linux `connect: auto` scouts, then verifies `{fleet}/_fleet/router` |
| Who is alive? | Application `presence` + `rosie fleet list` / `Fleet.robots()` (router announcement shown too) |
| Who sees whom? | Topic paths under `{fleet}/{robot}/…` and `{fleet}/_fleet/…` — subscribe only to what you need |

Host sessions default to `tcp/127.0.0.1:7447` (local `rosie router`). Override with
`ROSIE_CONNECT` or `connect=` only when the router runs on another machine.

## Fleet-native tooling

ROS 2 introspection and recording mostly assume a single coherent graph. Rosie
keys are `{fleet}/{robot}/…`, membership is `presence`, and one `rosie router`
sees every client. Host tools are **fleet-first**:

| Operation | Command |
|-----------|---------|
| Who is alive? | `rosie fleet list --fleet lab` |
| Team ready? | `rosie fleet wait --manifest fleet.json` (or `--expect id1,id2`) |
| Topics by robot | `rosie topic list --fleet lab` (alias: `rosie fleet topics`) |
| Echo | `rosie topic echo --fleet lab --key '*/pose'` |
| Record / play | `rosie bag record --fleet lab -o run.rosiebag` / `rosie bag play …` |
| Bag info | `rosie bag info run.rosiebag` |
| Export for analysis | `rosie bag export run.rosiebag -o run.mcap` |

Topic list and bag **listen for live traffic** (default window ~2s for list).
Publishers must be active; there is no separate DDS-style graph database.

Bags are fleet-scoped JSONL (optional `.gz`). Useful play/export flags:

```bash
rosie bag record --fleet lab -o run.rosiebag.gz --duration 30
rosie bag info run.rosiebag.gz
rosie bag play run.rosiebag.gz --key '*/pose' --start 5 --end 20
rosie bag export run.rosiebag.gz -o run.mcap --key '*/pose'
```

`--start` / `--end` are seconds from the bag’s first timestamp. `--key` is a
fleet-relative or absolute glob (same selectors as record/list).

Selectors are relative to the fleet unless absolute: `*/pose`, `car1/cmd_vel`,
`_fleet/estop`, or `**` for everything under the fleet.

## Team bring-up

Compose the team with a **fleet manifest** (JSON, or YAML if PyYAML is
installed). Example: [`examples/fleet-manifest.json`](../../examples/fleet-manifest.json).

```json
{
  "fleet": "lab",
  "connect": "tcp/192.168.8.2:7447",
  "robots": [
    {"id": "car1", "kind": "esp32-car", "status": "ready"},
    {"id": "car2", "kind": "esp32-car", "status": "ready"}
  ]
}
```

```bash
rosie fleet wait --manifest examples/fleet-manifest.json
# or without a file:
rosie fleet wait --fleet lab --expect car1,car2 --status ready
```

`Fleet.wait(...)` / `load_manifest(...)` / `resolve_manifest(...)` are the Python
APIs. Prefer `rosie fleet init` + `~/.rosie/fleets/<id>/` for day-to-day fleets
([Fleet management](management.md)). Manifest `defaults` / per-robot
`params` are for application code to read — Rosie does not push a remote
parameter server. MCU identity stays flash/env-fixed.

## Related docs

- [Fleet management](management.md) — init / add / router day-to-day
- [Security](security.md) — open vs secure modes, allowlist, ESP32 limits
- [Architecture](../architecture.md) — diagrams and SoftAP fallback notes
- [Conventions](../conventions.md) — robot / fleet topic paths
- [BYOR](../robots/byor.md) — standing up a new robot
- [Getting started](../getting-started.md) — host install and router
