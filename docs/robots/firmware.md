# Firmware (MCU / PlatformIO)

MCU path for Rosie: **PlatformIO / Arduino library** (ESP32 today; other
PlatformIO boards later) plus the **DiffDriveStack** assembly that turns
`robot.yaml` into a running mobile base. SoftAP Wi‑Fi is ESP32-specific and
**optional** (one-robot fleet on the robot AP). Multi-robot fleets should join
a dedicated AP as Wi‑Fi stations — see [Fleet networking](../fleet/networking.md).

Shared topics, modes, goto, and velocity PID: [Mobile base](mobile-base.md).
Linux peer: [Linux run](linux-run.md).

Prefer the Rosie CLI over raw `pio` commands:

```bash
pip install -e "/path/to/rosie/python[mcu]"   # once
rosie mcu setup   # from the robot project: links firmware + warms PIO
rosie mcu build
rosie mcu flash
rosie mcu monitor
```

`rosie mcu setup` / `build` / `flash` automatically find the Rosie
firmware library (from your editable install, or `ROSIE_FIRMWARE`) and create
`lib/rosie` in the project. They also run **`rosie mcu gen-config`** when
`robot.yaml` is present (writes `src/generated/robot_config.h`), and expose the
library via `PLATFORMIO_LIB_EXTRA_DIRS` (`~/.rosie/pio_libs`). Link only:
`rosie mcu link`.

`rosie mcu flash` / `monitor` autodetect a USB serial port (`--port` / `ROSIE_PORT`
to override). Pass-through: `rosie mcu build -- --verbose`. Raw `pio …` remains an
escape hatch.

## What you write

1. **`robot.yaml`** — identity, network, pins, geometry, gains.
2. **Thin `main.cpp`** using **`DiffDriveStack`** (recommended), or raw
   `MobileBase` for custom wiring.
3. Optional custom `cmd` ops via `stack.base().onCmd(...)`.

Scaffold a new project:

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot
# edit robot.yaml pins / SSID
rosie mcu setup && rosie mcu flash
rosie drive --config robot.yaml
```

## DiffDriveStack (recommended)

Include the generated header, then the stack:

```cpp
#include <Arduino.h>
#include "generated/robot_config.h"
#include <rosie/diff_drive_stack.h>

static rosie::DiffDriveStack g_stack;

void setup() {
  Serial.begin(115200);
  delay(300);
  // Optional: g_stack.base().onCmd("my_op", handler);
  g_stack.begin();
}

void loop() {
  g_stack.loop();
}
```

`rosie mcu build` / `gen-config` regenerates `robot_config.h` from `robot.yaml`.
`DiffDriveStack` wires the **selected** motors (`motors.driver`), optional
encoders / IMU / camera / range, DiffDrive kinematics, Wi‑Fi + Zenoh via
`rosie::mcuConnect`, SerialShell, `MobileBase`, and a `PidVelocityController`
(default gains `0,0,0` = open-loop `v_wheel / v_full`). See [Drivers](drivers.md) for
supported ids and pin keys (e.g. TB6612 `pwmA`/`ain1`… vs L298N `ena`/`in1`…).

Accessors: `stack.base()`, `stack.motors()` (`MotorDriver&`), `stack.kinematics()`,
`stack.velocityController()`; plus `stack.encoders()` / `stack.imu()` /
`stack.camera()` when those sections are present in YAML. Optional
`range.sensors` (up to 4) are brought up with shared `Wire` + XSHUT ordering and
registered on `MobileBase` before Zenoh `begin`.

You should not wire `ROSIE_*` macros by hand — `DiffDriveStack` consumes the
driver and pin macros emitted from `robot.yaml`. Optional onboard velocity PID:
`control.velocity` in YAML (default 0,0,0 = open-loop); tune live with
`rosie tune`. Optional raw sensor telemetry: `encoders.pub_hz` / `imu.pub_hz` /
`range.sensors` (`range/<id>` with raw + median-of-5).
`control.control_hz` sets the `control` topic rate (default 5 Hz).

Headers: `rosie/diff_drive_stack.h`, `rosie/mobile_base.h`, `rosie/velocity_controller.h`,
`rosie/motor_driver.h`, `rosie/diff_drive.h`,
`rosie/drivers/{motors,encoders,imu,camera,range}/*.h`, `rosie/mcu_connect.h`,
`rosie/wifi_station.h`, `rosie/serial_shell.h`.

## Alternative: raw `MobileBase`

If the chip is not in the MCU inventory (or not wired into `DiffDriveStack`
yet), implement `MotorDriver` / kinematics yourself and pass them into
`MobileBase`. Optionally attach a `VelocityController`. Keep using relative
topics so `rosie teleop` / `rosie drive` still work.

## Control loop

Inbox vs plant (why callbacks latch and the tick drives motors):
[Mobile base → Control loop timing](mobile-base.md#control-loop-timing).

On MCU those two sides are different FreeRTOS tasks:

| Who | Thread | Job |
|-----|--------|-----|
| zenoh-pico **read task** | Started by `Session::open()` (`-DZ_FEATURE_MULTI_THREAD=1` required) | As soon as a sample arrives, run the subscriber callback: parse, stamp, latch into `cmd_` (mutex). No motors. |
| zenoh-pico **lease task** | Same `open()` | Session keep-alive (not motion). |
| Arduino `loop()` → `DiffDriveStack::loop()` → `MobileBase::spin()` | Main sketch | USB `SerialShell`, then timed `tick()` + telemetry pubs. |

`spin()` does **not** drain Zenoh. It only runs `tick()` every `control.dt_ms`
(odometry, mode arbiter, motors) and publishes `pose` / `presence` / … at their
`*_hz` rates. MCU publishers never use blocking congestion control from
`tick()`.

| When | What |
|------|------|
| Wire arrival (read task) | Callbacks latch `cmd_vel` / `goto` / `cmd` into `cmd_` (mutex) |
| Every `control.dt_ms` | `tick()` — odometry, mode arbiter, motors |
| At `pose_hz` / `control_hz` / … | Telemetry publishers |

## Add the library (automatic vs manual)

**Preferred:** from the robot project, `rosie mcu setup` or
`rosie mcu link` — no hand-edited paths.

**Manual escape hatches** (if you use raw `pio` without the Rosie CLI):

1. Symlink: `lib/rosie` → `path/to/rosie/firmware` (relative or absolute), or
2. Set `lib_extra_dirs` to a folder that *contains* the `firmware` library
   directory (or use `~/.rosie/pio_libs` after `rosie mcu link`).

Also depend on **zenoh-pico** and **ArduinoJson** (see your robot’s `platformio.ini`).

Recommended build flags:

```ini
build_flags =
    -DZENOH_COMPILER_GCC
    -DZ_FEATURE_MULTI_THREAD=1
    -DZ_FEATURE_PUBLICATION=1
    -DZ_FEATURE_SUBSCRIPTION=1
```

Robot projects can live anywhere; they only need a path to this library. See [BYOR](byor.md).

## SoftAP / station + Session (advanced)

For a **single** robot with no travel router, use SoftAP. For fleets, join a
dedicated AP as a station — [Fleet networking](../fleet/networking.md).

Prefer **`rosie::mcuConnect`** when you want the same Wi‑Fi + Zenoh retry policy
as `DiffDriveStack` without assembling motors:

```cpp
#include <rosie/mcu_connect.h>
#include <rosie/session.h>

rosie::Session session("robot");

void setup() {
  Serial.begin(115200);
  rosie::McuConnectConfig cfg;
  cfg.network_mode = "softap";       // or "station"
  cfg.wifi_ssid = "MyRobot-AP";
  cfg.wifi_password = "password";
  cfg.zenoh_connect = "tcp/192.168.4.2:7447";  // or the locator baked by codegen (`connect: auto`)
  cfg.zenoh_mode = "client";
  if (!rosie::mcuConnect(session, cfg)) {
    Serial.println("Zenoh not up — USB still works");
  }
  // createPublisher / createSubscription …
}
```

Raw helpers (custom glue that does not want retries):

```cpp
#include <rosie/wifi_softap.h>   // or wifi_station.h
#include <rosie/session.h>
```

Raw Session sketch without `mcuConnect` (advanced / non-mobile):

```cpp
#include <rosie/wifi_softap.h>
#include <rosie/session.h>
#include <ArduinoJson.h>

rosie::Session session("robot");  // optional second arg: fleet id
int pubPose = -1;

void onCmdVel(const uint8_t* data, size_t len, void* /*user*/) {
  // parse JSON Twist from data/len
}

void setup() {
  Serial.begin(115200);
  rosie::softAP("MyRobot-AP", "password", 1);

  if (!session.open("tcp/192.168.4.2:7447", "client")) {
    Serial.println("zenohd not reachable yet");
    return;
  }

  pubPose = session.createPublisher("pose");
  session.createSubscription("cmd_vel", onCmdVel);
}

void loop() {
  JsonDocument doc;
  doc["x"] = 0.0;
  doc["y"] = 0.0;
  doc["theta"] = 0.0;
  session.publishJson(pubPose, doc);
  delay(50);
}
```

Use **relative** names (`"pose"`) or absolute (`"/global/estop"`). Same rules as
Python. Application code should not include `<zenoh-pico.h>` directly.

Typed messages (after codegen): `#include <rosie/std_msgs.h>` → `rosie::msg::Twist`, etc. See [Messages](../messages.md).

## API surface

| Method | Role |
|--------|------|
| `Session(robot, fleet)` / `setIdentity` | Robot and fleet for relative names |
| `getRobot` / `getFleet` / `hasFleet` | Identity accessors |
| `resolveName(name, out, len)` | Relative → `{fleet}/{robot}/name` |
| `resolveFleetName(name, out, len)` | → `{fleet}/_fleet/name` (requires fleet) |
| `open(locator, mode)` | Connect to `zenohd` (usually `"client"`); starts background tasks |
| `ready()` | Session opened successfully |
| `createPublisher(name)` | Relative/absolute name; returns pub id `>= 0`, or `-1` |
| `createFleetPublisher(name)` | Fleet-scoped publisher |
| `createSubscription(name, cb, user)` | Raw-bytes callback |
| `createFleetSubscription(name, cb, user)` | Fleet-scoped subscriber |
| `publish` / `publishStr` | Raw bytes or C string |
| `publishJson(pub_id, doc)` | JSON + auto `stamp` |

Wi‑Fi helpers (ESP32): `rosie::softAP(ssid, password, channel = 1)` (one-robot
fleet); `rosie::wifiStation(ssid, password, timeout_ms)` (dedicated AP).
Shared bring-up: `rosie::mcuConnect(session|base, cfg)` — SoftAP or station,
then Zenoh open/`MobileBase::begin` with retries (same policy as DiffDriveStack).

## Limits

| Limit | Value |
|-------|--------|
| Publishers per session | 8 |
| Subscribers per session | 8 |
| Max key length | 128 |
| `publishJson` buffer | ~384 bytes |
| `Log` / `Cmd` / presence string fields | 64 chars each (generated C++ structs) |

Stay within these for MCU SoftAP / Wi‑Fi payloads. Larger blobs (JPEG) should use raw `publish`, not JSON.

A complete robot lives in a **separate** project that depends on this library — not inside Rosie. See [BYOR](byor.md).
