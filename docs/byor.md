# Bring Your Own Robot (BYOR)

Checklist for standing up a new MCU (or Linux) robot on Rosie.

For shared names and units, see [Conventions](conventions.md). For networking,
see [Fleet networking](fleet-networking.md). For the batteries-included ground
base path, see [Mobile base](mobile-base.md) and [Drivers](drivers.md).

## 1. Install Rosie

```bash
pip install -e "/path/to/rosie/python[mcu]"
rosie setup                 # fetch zenohd while online
```

## 2. Scaffold the project

```bash
mkdir mybot && cd mybot
rosie mcu init --robot mybot
```

That writes `robot.yaml`, a thin `DiffDriveStack` `src/main.cpp`, links
`lib/rosie`, and generates `src/generated/robot_config.h`.

Or from an existing folder: `rosie mcu setup` after you add `robot.yaml`.

## 3. Edit `robot.yaml`

Set pins, SSID/password, geometry, and gains. Inventory of driver ids:
`rosie drivers list` / [Drivers](drivers.md).

You do **not** hand-edit `ROSIE_*` constants — regenerate with
`rosie mcu gen-config` (also runs on every `rosie mcu build`).

## 4. Firmware

Default sketch (from `rosie mcu init`):

```cpp
#include "generated/robot_config.h"
#include <rosie/diff_drive_stack.h>

static rosie::DiffDriveStack g_stack;

void setup() {
  Serial.begin(115200);
  delay(300);
  g_stack.begin();
}

void loop() {
  g_stack.loop();
}
```

Optional: `g_stack.base().onCmd("my_op", handler);` before `begin()`.

```bash
rosie mcu build
rosie mcu flash
rosie mcu monitor
```

Raw `rosie::Session` / `MobileBase` remain valid for advanced / non-diff-drive
robots.

## 5. Host side

```bash
rosie drive --config robot.yaml     # REPL: waypoints, teleop, camera, …
rosie teleop --robot mybot          # WASD only
rosie tune --config robot.yaml      # optional: live velocity PID
```

Drive REPL commands, flags, and the Python `Robot` API:
[Mobile base → Host](mobile-base.md#host).

## 6. Bring-up order

### Fleet (dedicated AP)

1. Install + `rosie setup` (+ `rosie mcu setup`) on normal internet.
2. Power the dedicated AP; join laptop + robots as stations (`network.mode: station`).
3. `rosie router` on the laptop (or Pi).
4. Confirm each robot’s Zenoh locator; reset MCUs if needed.
5. `rosie fleet list --fleet <id>` / `rosie drive` / teleop.

### Solo SoftAP fallback

1. Install + `rosie setup` on normal Wi‑Fi.
2. Join the robot SoftAP; confirm host IP (often `192.168.4.2`).
3. `rosie router`
4. Reset the MCU if it raced ahead of the router.
5. `rosie drive` / teleop.

## 7. Escape hatch

Chip not in the inventory? Implement `MotorDriver` (or sensor helpers) in your
project and construct `MobileBase` yourself (skip `DiffDriveStack`). Document
custom `cmd` ops in your robot README.

## 8. What goes in the robot README

- Network mode, robot id, optional fleet, Zenoh locator
- That config lives in `robot.yaml`
- Board / `rosie mcu flash` notes
- Any custom `cmd` ops beyond MobileBase defaults (`stop`, `zero`, `set_gains`, …)
- Whether velocity PID is used (`control.velocity`) and how to retune
