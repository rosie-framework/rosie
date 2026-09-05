# Security

Layered security model for Rosie buses. Day-to-day fleet commands:
[Fleet management](management.md). Wi‑Fi topology:
[Fleet networking](networking.md).

## Threat model

**Assets.** Motion and estop commands on the bus, robot identity / presence,
and the fleet shared secret when secure mode is on.

**Trust boundary.** Anyone who can join the Wi‑Fi or SoftAP is on the same
LAN as the bus. Network isolation (SoftAP, dedicated travel AP, VLAN) is the
first control — see [Fleet networking](networking.md).

| Mode | Who can use the bus | What host tools treat as “in the fleet” |
|------|---------------------|-----------------------------------------|
| **Open** (default) | Anyone on the SSID | Whoever is publishing `presence` |
| **Secure** (`--secure`) | Peers that know the shared secret (Zenoh usrpwd) | Enrolled ids only (`fleet add` allowlist) |

Open mode is required for MCU fleets today (zenoh-pico has no usrpwd —
see [ESP32 guidance](#esp32-guidance)). **Secure mode is the recommended
default for Linux / host agents** on shared, campus, or field networks.
Holding the secret still allows publishing under any `robot` id until per-key
ACLs or app-layer signing land (see Layers below).

## Layers (present + future)

| Layer | Status | What it does |
|-------|--------|--------------|
| **Network isolation** | Present | SoftAP, VLAN, or dedicated travel AP — strangers off the SSID |
| **Bus mode: open vs secure** | Present (host/Linux) | Zenoh usrpwd when `--secure`; open by default |
| **Fleet allowlist** | Present (host tools) | Manifest enrollment filters `fleet list` / `topics` **only in fleet-secure** |
| **App-layer HMAC / signed commands** | Future | MCU-friendly auth without transport usrpwd |
| **Payload encryption / TLS** | Future | Confidentiality beyond shared LAN trust |
| **Per-key Zenoh ACLs** | Future | Stop secret-holders from spoofing another `robot` id |

## Two modes

| Mode | Router | Bus auth | Allowlist on `fleet list` etc. |
|------|--------|----------|--------------------------------|
| Fleet open | `rosie router --fleet X` | No | No |
| Fleet secure | `rosie router --fleet X --secure` | Yes | Yes (needs prior `fleet add`) |

**Secure** means: bus auth, and host-tool allowlisting.
**Open** (default) has neither. Mode is **CLI-flag driven**.

A fleet is always required. Create it before the router:
`rosie fleet init --fleet X`.

### Commands vs roles

| Command | Role |
|---------|------|
| `rosie fleet init --fleet X` | Create fleet home (`manifest.yaml`; secret only with `--secure`) |
| `rosie fleet add --fleet X …` | Enroll robot ids (allowlist in **secure** mode) |
| `rosie router --fleet X` | Start zenohd for that fleet (requires the home to exist) |
| `rosie fleet list --fleet X` | Host discovery against the live bus |

`fleet init` does **not** start the router. `router --fleet X` does **not**
create the fleet.

### Fleet open (ESP32 / SoftAP / MCU field)

```bash
rosie fleet init --fleet demofleet
rosie fleet add --fleet demofleet --robot car1
rosie router --fleet demofleet              # open bus (no auth)
rosie fleet list --fleet demofleet          # no allowlist filter
```

### Fleet secure (Linux / host agents)

```bash
rosie fleet init --fleet lab --secure
rosie fleet add --fleet lab --robot bot1
rosie router --fleet lab --secure
rosie fleet list --fleet lab --secure       # allowlist + usrpwd session
```

Write secrets into yaml with `rosie secret apply` (or keep an existing
`network.fleet_secret` and rebuild). Host tools that talk to a secure router
need `--secure` (or an explicit password / `ROSIE_FLEET_SECRET`).

## ESP32 guidance

zenoh-pico does **not** implement Zenoh usrpwd today. That is a real constraint
on using MCUs in the field: MCU fleets must stay on **fleet open**. Passing
`--secure` on the router will reject ESP32 clients even when the password hash
matches what you baked into firmware.

When you need MCU auth later, prefer an **app-layer** HMAC on commands rather
than waiting for pico transport auth. Mixed MCU + Linux fleets that need
secure Linux members should isolate the MCU bus (dedicated AP) rather than
opening the Linux bus.

## Operator checklist

| Situation | Mode |
|-----------|------|
| One ESP32 SoftAP desk demo | Fleet open |
| Several ESP32s on a travel AP (MCU cannot do usrpwd) | Fleet open |
| Linux robots / host agents on shared, campus, or field Wi‑Fi | Fleet **secure** |
| Independent research fleets co-located at a field site | Fleet secure (+ enroll with `fleet add`) |

## Related docs

- [Fleet management](management.md) — init / add / router day-to-day
- [Fleet networking](networking.md) — SoftAP vs dedicated AP
- [Conventions](../conventions.md) — `(fleet, robot)` identity
- [Getting started](../getting-started.md)
