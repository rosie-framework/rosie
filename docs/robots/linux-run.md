# Linux run (`rosie run`)

Native Linux path for Rosie: drive a Pi / Jetson / DIY base directly from
`robot.yaml` (no ROS). `MobileBaseRuntime` honors the same
[Mobile base](mobile-base.md) contract as MCU `DiffDriveStack` — topics, modes,
deadman, goto, velocity PID, `set_gains` / `get_gains`, `heading_source`, and
camera.

MCU peer: [Firmware](firmware.md).

## Install

```bash
pip install "rosie-framework[linux]"   # built-in tb6612 / gpio / mpu6050 / pca9685
# or from a checkout:
# pip install -e "/path/to/rosie/python[linux]"
```

For USB / V4L2 camera capture also install the camera extra (OpenCV). Pi CSI
cameras use apt `python3-picamera2` — see [Camera](camera.md).

```bash
pip install "rosie-framework[camera]"   # v4l2 backend + host viewers
```

## `robot.yaml`

```yaml
platform: linux
robot: pi1
fleet: lab
network:
  connect: tcp/192.168.8.2:7447
base:
  type: diff_drive
  wheel_diameter: 0.068
  wheel_base: 0.13
  ticks_per_rev: 1440
motors:
  driver: tb6612          # same chip as the ESP32 car; pins are Pi BCM
  pins: { pwmA: 12, ain1: 5, ain2: 6, pwmB: 13, bin1: 20, bin2: 21 }
  pwm: { freq: 20000, min: 0.1, max: 1.0 }
# encoders:               # optional; without them, pose is dead-reckoned
#   driver: gpio_quadrature
#   pins: { left: [17, 18], right: [22, 23] }
#   pub_hz: 10
# imu:
#   chip: mpu6050
#   i2c: { bus: 1, addr: 0x68 }
#   pub_hz: 10
# range:                    # optional ToF; free-form ids → range/<id>
#   i2c: { bus: 1 }
#   pub_hz: 10
#   sensors:
#     front_left:
#       chip: vl53l1x          # or: vl53l0x
#       i2c: { addr: 0x29 }
#       xshut: 7            # required when >1 VL53 on the bus
#     front_right:
#       chip: vl53l0x
#       i2c: { addr: 0x30 }
#       xshut: 8
# camera:
#   driver: picamera2     # or: v4l2 | python
#   width: 640
#   height: 480
#   jpeg_quality: 70      # 0–100, higher = better
#   pub_hz: 2
#   enable_default: true
control:
  dt_ms: 20
  teleop: { timeout_ms: 400, kv: 180, kw: 40 }
  goto: { kp_linear: 0.8, kp_angular: 1.5, v_max: 0.35, w_max: 1.5 }
  velocity:               # optional; omit for open-loop only
    type: pid
    kp: 0.0
    ki: 0.0
    kd: 0.0
    i_clamp: 0.5
  control_hz: 5
  pose_hz: 20
  presence_hz: 1
```

Shared sections (`robot`, `fleet`, `network.connect`, `base`, `control`,
`camera` / `range` knobs like `pub_hz`) port from MCU YAML; pin blocks,
`camera.driver`, and `range` I2C `bus` / `xshut` are Linux-specific. Inventory:
`rosie drivers list --platform linux` · [Drivers](drivers.md).

## CLI

```bash
rosie run --config robot.yaml --dry-run   # validate + probe drivers; no hardware
rosie run --config robot.yaml             # foreground control loop
```

`--dry-run` prints platform / identity / hardware summary and import probes
(`lgpio`, `smbus2`, picamera2 / OpenCV, BYO class resolution) without opening
GPIO/I2C/camera/range or Zenoh.

Config and saved gains take effect on the next process start — restart
`rosie run` after editing YAML (no reflash). Live `set_gains` still applies
immediately while the process is running.

## Camera

When `camera:` is present, `MobileBaseRuntime` opens a `CameraSource` and
publishes JPEG bytes on `camera/compressed` (BULK) from a daemon thread at
`camera.pub_hz`. `camera_enable` on `cmd` toggles streaming; init failure logs
and continues headless.

| Driver | Notes |
|--------|-------|
| `picamera2` | Pi CSI. `sudo apt install -y python3-picamera2`; use a venv with `--system-site-packages` |
| `v4l2` | USB webcam via OpenCV (`rosie-framework[camera]`); optional `device` |
| `python` | BYO class with `read_jpeg()` / `close()` (`camera.class`) |

Full wire format, quality scale, and host tools: [Camera](camera.md).

## Range (ToF)

When `range.sensors` is present, `MobileBaseRuntime` opens each sensor and
publishes `Range` on `range/<id>` (STREAM) at that sensor’s `pub_hz`. Messages
include raw `range` and onboard `range_median` (last 5 successful samples).
Init failure for one sensor logs and continues the others. Multi VL53L0X /
VL53L1X on one bus needs per-sensor `xshut` and unique `i2c.addr` — see
[Drivers](drivers.md).

## BYO drivers

No `rosie-framework[linux]` needed if you supply Python drivers:

```yaml
motors:
  driver: python
  class: mypkg.motors:MyMotorDriver   # set_channels / stop / close
```

Same pattern for `encoders.driver: python`, `imu.chip: python`,
`camera.driver: python`, and `range.sensors.*.chip: python` (`read_range` /
`close`). Prefer a `from_config` classmethod when present.
Optional pose-zero hooks: `EncoderReader.zero()` and `ImuReader.recalibrate()`
(called via `getattr` — omit if unused).

## Control loop

The main thread runs the control tick every `control.dt_ms` and rate-limited
publishers (`pose`, `presence`, `control`, optional `encoders` / `imu` /
`range/<id>`). Camera publishes on its own thread. Zenoh subscriber callbacks
latch `cmd_vel` / `goto` / `cmd` under a lock (or run gain / heading /
camera_enable handlers immediately). `SIGINT` / `SIGTERM` stop motors and close
the session.

Shared latch-vs-actuate semantics and command precedence:
[Mobile base → Control loop timing](mobile-base.md#control-loop-timing).

## Dead-reckoning without encoders

Unlike MCU DiffDrive kinematics (which require ticks), Linux integrates the
last commanded Twist when no encoder reader is present. Prefer encoders for
real navigation; dead-reckoning is for bring-up and simple demos.

## Not supported yet

| Feature | Status |
|---------|--------|
| SerialShell (USB REPL) | MCU only |

## Related

- [Mobile base](mobile-base.md) — shared contract, topics, host tools
- [Camera](camera.md) — JPEG wire format, quality scale, host viewers
- [BYOR](byor.md) — Linux bring-up checklist
- [Bridges](bridges.md) — when to use `rosie agent` instead
- [Drivers](drivers.md) — inventory
