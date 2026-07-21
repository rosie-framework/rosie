# Firmware (MCU / PlatformIO)

Rosie firmware is a **PlatformIO / Arduino library** aimed at ESP32 today, with
the same tooling path available for other PlatformIO MCUs later (RP2040, STM32,
…). SoftAP Wi‑Fi helper code is ESP32-specific and **optional** (solo-robot
fallback). Fleets should join a dedicated AP as Wi‑Fi stations — see
[Fleet networking](fleet-networking.md).

Prefer the Rosie CLI over raw `pio` commands. MCU tooling lives under
``rosie mcu …`` — use that for ESP32 (and other PlatformIO boards). Raspberry
Pi / Jetson / laptop hosts use ``rosie setup`` and Python sessions, not this
group.

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

## MobileBase / DiffDriveStack (recommended for ground robots)

Prefer [Mobile base](mobile-base.md):

1. Write `robot.yaml` (or `rosie mcu init`).
2. Thin `main.cpp`: `#include "generated/robot_config.h"` then
   `<rosie/diff_drive_stack.h>` → `DiffDriveStack::begin()` / `loop()`.
3. `rosie mcu build` regenerates config and compiles.

You should not wire `ROSIE_*` macros by hand — `DiffDriveStack` consumes them.
Optional onboard velocity PID: `control.velocity` in YAML (default 0,0,0 =
open-loop); tune live with `rosie tune`. Driver inventory: [Drivers](drivers.md)
/ `rosie drivers list`.

Headers: `rosie/diff_drive_stack.h`, `rosie/mobile_base.h`, `rosie/velocity_controller.h`,
`rosie/motor_driver.h`, `rosie/diff_drive.h`, `rosie/drivers/*.h`, `rosie/wifi_station.h`,
`rosie/serial_shell.h`.

## SoftAP / station + Session (advanced)

For a **single** robot with no travel router, use SoftAP. For fleets, join a
dedicated AP as a station — [Fleet networking](fleet-networking.md).

```cpp
#include <rosie/wifi_softap.h>   // or wifi_station.h
#include <rosie/session.h>
```

Raw Session sketch (advanced / non-mobile):

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
  session.poll();
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

Typed messages (after codegen): `#include <rosie/std_msgs.h>` → `rosie::msg::Twist`, etc. See [Messages](messages.md).

## API surface

| Method | Role |
|--------|------|
| `Session(robot, fleet=nullptr)` / `setIdentity` | Robot (+ optional fleet) for relative names |
| `getRobot` / `getFleet` / `hasFleet` | Identity accessors |
| `resolveName(name, out, len)` | Relative → `{robot}/name` or `{fleet}/{robot}/name` |
| `resolveFleetName(name, out, len)` | → `{fleet}/_fleet/name` (requires fleet) |
| `open(locator, mode)` | Connect to `zenohd` (usually `"client"`); starts background tasks |
| `ready()` | Session opened successfully |
| `poll()` | Drive Zenoh / callbacks from the Arduino loop |
| `startBackgroundTasks()` | Called by `open`; rarely needed directly |
| `createPublisher(name)` | Relative/absolute name; returns pub id `>= 0`, or `-1` |
| `createFleetPublisher(name)` | Fleet-scoped publisher |
| `createSubscription(name, cb, user)` | Raw-bytes callback |
| `createFleetSubscription(name, cb, user)` | Fleet-scoped subscriber |
| `publish` / `publishStr` | Raw bytes or C string |
| `publishJson(pub_id, doc)` | JSON + auto `stamp` |

Wi‑Fi helpers (ESP32): `rosie::softAP(ssid, password, channel = 1)` (solo
fallback); `rosie::wifiStation(ssid, password, timeout_ms)` (fleet / dedicated AP).

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
