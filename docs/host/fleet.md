# Fleet (Python)

Host-side view of a **fleet**: presence discovery, bring-up wait, topic map,
estop, and leader claims. Owns its own Zenoh connection (not a robot
[`Session`](writing-sessions.md)). Fleet-wide topics live under
`{fleet}/_fleet/...`; robot presence is `{fleet}/{robot}/presence`.

CLI mirrors: `rosie fleet list` / `wait` / topics / estop / leader — see
[Fleet management](../fleet/management.md).

`Fleet` is for **coordination**. Per-robot drive / teleop uses
[`MobileRobot`](mobile-robot.md) or a raw `Session` for each id.

## Construct

`with` auto-closes on exit. You can also keep long-lived instances and call
`close()` yourself.

```python
from rosie import Fleet, MobileRobot

with Fleet("lab", connect="tcp/192.168.8.2:7447") as fleet:
    fleet.wait(["car1", "car2"])
    print([p.robot_id for p in fleet.robots()])
    fleet.publish_estop()

with MobileRobot(robot="car1", fleet="lab", connect="tcp/192.168.8.2:7447") as bot:
    bot.drive_to(1.0, 0.0)

# Long-lived — call methods later; close when finished
fleet = Fleet("lab", connect="tcp/192.168.8.2:7447")
bot = MobileRobot(robot="car1", fleet="lab", connect="tcp/192.168.8.2:7447")
fleet.wait(["car1", "car2"])
bot.drive_to(1.0, 0.0)
bot.close()
fleet.close()
```

### Constructor kwargs

| Kwarg | Role |
|-------|------|
| `fleet` | Fleet id (required; no `/`) |
| `connect` | Zenoh locator (default via `ROSIE_CONNECT` / localhost) |
| `allowlist` | Optional set of enrolled robot ids; filters `robots()` / `topics()` |
| `user` / `password` | Optional Zenoh usrpwd (secure fleets) |
| `secure` | Prefer secure open when no password |

## Methods

### Who is on the bus?

| Method | Use when |
|--------|----------|
| `robots(ttl_s=3, wait_s=0.5)` | Snapshot “who is alive right now?” (fresh `presence`). Same idea as `rosie fleet list`. |
| `ignored_robots(…)` | Secure fleets: who is advertising presence but **not** enrolled (not on the allowlist)? |
| `topics(wait_s=2)` | Debug / inspect: which keys are talking under the fleet? Same idea as `rosie topic list --fleet`. Returns a `TopicMap`. |

`robots()` / `topics()` honor `allowlist` when set (omit strangers unless `include_all=True`). Presence older than `ttl_s` is dropped as stale.

### Bring-up gate

| Method | Use when |
|--------|----------|
| `wait(["car1", "car2"], timeout_s=30)` | Scripted demos: block until the expected team is present before you teleop / drive. Raises `TimeoutError` if not ready in time. Same idea as `rosie fleet wait`. |
| `wait(manifest, …)` | Same, but roster (+ optional per-robot `status`) comes from a `FleetManifest`. |

### Safety / coordination

| Method | Use when |
|--------|----------|
| `publish_estop()` | Stop the whole team: broadcast estop on `{fleet}/_fleet/estop` (robots that subscribe must honor it). |
| `claim_leader(robot_id, term=1)` | Appoint a soft leader for app-level coordination (not motor arbitration). Publishes `{fleet}/_fleet/coord/leader`. |
| `get_leader(wait_s=0.5)` | Read the latest leader claim (after someone called `claim_leader`, or another host did). |

Leader is optional application convention — Rosie does not elect a leader for you.

### Keys / lifecycle

| Method | Use when |
|--------|----------|
| `fleet_key("estop")` | Build `{fleet}/_fleet/<rel>` for a fleet-scoped publish/subscribe. |
| `resolve_key("car1/pose")` | Prefix a relative key with the fleet (`lab/car1/pose`), or pass through absolute keys. |
| `close()` / `with Fleet(...)` | Always close when done (drops Zenoh subs). Prefer the context manager. |

`TopicMap.by_robot` maps robot id (or `_fleet`) → relative topic suffixes; `.flat()` lists full keyexprs.

## Related

- [MobileRobot](mobile-robot.md) — per-robot MobileBase control
- [Writing sessions](writing-sessions.md) — raw `Session` / `publish_fleet`
- [Fleet management](../fleet/management.md) — CLI bring-up, allowlist, secrets
- [Fleet networking](../fleet/networking.md) — dedicated AP vs SoftAP
- [Conventions](../conventions.md) — identity and fleet robot contract
