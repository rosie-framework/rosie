# Messages & codegen

Message schemas live in one place:

```
interfaces/std_msgs.yaml
```

That YAML is the source of truth. This page is the human catalog — keep both in sync when fields change.

Generate Python + C++ bindings (from the Rosie repo root):

```bash
python3 interfaces/gen.py
```

This writes:

- `python/rosie/std_msgs.py`
- `firmware/include/rosie/std_msgs.h`

Commit the generated files so PlatformIO builds do not require Python at compile time.

## Adding a message

1. Edit `std_msgs.yaml`
2. Run `gen.py`
3. Update this catalog
4. Use the new type from Python (`from rosie.std_msgs import ...`) or C++ (`rosie::msg::...`)

Supported field types: `f32`, `f64`, `bool`, `str`, `i32`, `u32`. Optional fields: append `?` (e.g. `value: f32?`).

## Stamp

Every generated message includes a top-level `stamp` (seconds).
`Session.publish` / `publish_msg` / `publishJson` fill it when missing.

There is no nested `header`, no `seq`, and no ROS-style `frame_id`. See [Architecture](architecture.md) for stamp clock semantics (laptop wall time vs MCU `millis()/1000.0`).

Plain JSON dicts are first-class on the wire — typed classes are optional convenience. Robots may publish **extra JSON fields** alongside the standard ones (e.g. `mode` on pose). Prefer keeping the std fields present so generic tools still work.

## Catalog

### Twist

Planar body velocity. Typical topic: `<robot>/cmd_vel`.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `v` | `f32` | Linear speed along robot forward (m/s); + forward, − reverse |
| `w` | `f32` | Yaw rate about vertical (rad/s); + left/CCW, − right/CW |

```json
{ "stamp": 1.0, "v": 0.2, "w": 0.0 }
```

### Pose2D

Planar pose estimate. Typical topic: `<robot>/pose`.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `x` | `f32` | meters |
| `y` | `f32` | meters |
| `theta` | `f32` | yaw radians; frame/convention is robot-defined |

```json
{ "stamp": 1.0, "x": 0.0, "y": 0.0, "theta": 0.0 }
```

**MobileBase** also publishes stable extras on `pose`: `heading_deg`, `dist`,
`navigating`, `mode`, `goal_id` (while navigating), and optionally `imu_ok` /
`imu_heading`. Progress is on `pose`; terminal outcome is on `nav_result`.
`MobileRobot.drive_to` waits for a matching `nav_result`. See
[Conventions](conventions.md) and
[Mobile base → Navigation helpers](robots/mobile-base.md#navigation-helpers).

### Log

Human-readable status line. Typical topic: `<robot>/log`.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `level` | `str` | e.g. `"info"`, `"warn"`, `"error"` (convention, not enforced) |
| `msg` | `str` | free-form text |

```json
{ "stamp": 1.0, "level": "info", "msg": "ready" }
```

On the MCU, `level` / `msg` string buffers are capped at **64** characters.

### Cmd

Discrete command / mode switch. Typical topic: `<robot>/cmd`.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `op` | `str` | command name |
| `value` | `f32?` | optional numeric argument |

Common ops on MobileBase / DiffDriveStack: `"stop"`, `"zero"`, `"set_gains"`,
`"get_gains"`, plus optional `"heading_source"`, `"camera_enable"`. Robots may
define their own.

`set_gains` takes a JSON object value (partial OK):

```json
{ "op": "set_gains", "value": { "kp": 0.3, "ki": 0.0, "kd": 0.0, "i_clamp": 0.5 } }
```

```json
{ "stamp": 1.0, "op": "stop" }
```

### Control (MobileBase telemetry)

Published on `<robot>/control` when a `VelocityController` is attached (~5 Hz).

| Field | Type | Meaning |
|-------|------|---------|
| `kp`, `ki`, `kd`, `i_clamp` | `f32` | current velocity PID gains |
| `mode` | `str` | `idle` / `manual` / `auto` |
| `target_vel` | `f32[]` | per-wheel target velocity (m/s) |
| `meas_vel` | `f32[]` | per-wheel measured velocity (m/s) |

Tune live with `rosie tune` / `MobileRobot.set_gains`.

### Goto

Planar goal point in the same frame as `Pose2D`. Typical topic: `<robot>/goto`.
Latest goal wins. Hosts should set `goal_id`; if omitted, MobileBase assigns
one. Completion is published on `nav_result` (not inferred from `pose` alone).
See [Mobile base → Navigation helpers](robots/mobile-base.md#navigation-helpers).

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `x` | `f32` | meters |
| `y` | `f32` | meters |
| `goal_id` | `i32?` | attempt id (echoed on pose + nav_result) |

```json
{ "stamp": 1.0, "x": 1.0, "y": 0.5, "goal_id": 3 }
```

### NavResult

Terminal outcome of a `goto` attempt. Typical topic: `<robot>/nav_result`.
Published once when AUTO navigation ends.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `goal_id` | `i32` | attempt id from `Goto` (or robot-assigned) |
| `status` | `str` | `"succeeded"` / `"canceled"` / `"aborted"` |
| `x` | `f32?` | pose at completion (meters) |
| `y` | `f32?` | pose at completion (meters) |

```json
{ "stamp": 1.0, "goal_id": 3, "status": "succeeded", "x": 1.002, "y": 0.498 }
```

### RobotPresence

Membership / heartbeat. Typical topic: `<robot>/presence` (or `<fleet>/<robot>/presence`).

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `robot_id` | `str` | This robot's id |
| `fleet_id` | `str?` | Optional fleet id |
| `status` | `str` | e.g. `"ready"`, `"fault"`, `"offline"` |

```json
{ "stamp": 1.0, "robot_id": "car1", "status": "ready" }
```

### LeaderClaim

Fleet coordinator claim. Typical topic: `<fleet>/_fleet/coord/leader`.

| Field | Type | Meaning |
|-------|------|---------|
| `stamp` | `f64` | Seconds (auto-filled when missing) |
| `robot_id` | `str` | Claimant robot id |
| `term` | `u32` | Election term (higher wins) |

```json
{ "stamp": 1.0, "robot_id": "car1", "term": 1 }
```

## Wire format notes

- Structured msgs: UTF-8 JSON over Zenoh.
- Firmware `publishJson` serializes into a fixed buffer (~**384** bytes) — keep payloads small.
- Prefer these schemas for cross-robot contracts; robot-specific payloads can still use plain JSON dicts when needed.
- Topic naming: [Conventions](conventions.md).
