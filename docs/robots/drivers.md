# Drivers & inventory

Catalog of `robot.yaml` type strings. Same data as `firmware/drivers/registry.yaml`
and `rosie drivers list`. Entries are tagged with **platforms** (`mcu`, `linux`,
or both).

```bash
rosie drivers list
rosie drivers list --platform linux
rosie drivers list --category motors --platform mcu
```

MCU `DiffDriveStack` selects motors / encoders / IMU / camera from these ids at
compile time (`rosie mcu gen-config`). Linux `rosie run` selects at runtime.

## Motors (`motors.driver`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `tb6612` | mcu, linux | supported | TB6612FNG dual H-bridge; pins `pwmA,ain1,ain2,pwmB,bin1,bin2` (+ `pwm`) |
| `l298n` | mcu | supported | L298N dual H-bridge; pins `ena,in1,in2,enb,in3,in4` (+ `pwm`) |
| `pca9685` | linux | supported | I2C PWM HAT (magnitude PWM) |
| `python` | linux | supported | BYO `MotorDriver` via `motors.class` |
| `drv8833` | mcu | planned | BYO via `MotorDriver` / raw `MobileBase` until supported |

## Encoders

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `quad_encoder` | mcu | supported | Quadrature A/B via ESP32Encoder (`encoders.pins`); default when `encoders:` present |
| `gpio_quadrature` | linux | supported | Quadrature A/B via Pi GPIO (`lgpio`) |
| `python` | linux | supported | BYO `EncoderReader` via `encoders.class` |

Omit `encoders` on MCU or Linux for dead-reckoning odometry (commanded twist,
optional IMU yaw). Set `encoders.pub_hz` (e.g. `10`) to publish cumulative
ticks on the `encoders` topic; omit or `0` keeps them onboard-only.

## IMU (`imu.chip`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `mpu6050` | mcu, linux | supported | Accel + gyro; yaw-rate used for odometry fusion |
| `python` | linux | supported | BYO `ImuReader` via `imu.class` |

Set `imu.pub_hz` (e.g. `10`) to publish 6-axis samples (`accel_*` m/s²,
`gyro_*` rad/s) on the `imu` topic; omit or `0` keeps them onboard-only.
## Camera (`camera.board`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `esp32s3_eye` | mcu | supported | ESP32-S3-EYE DVP pinout (also Freenove ESP32-S3 CAM clones). Alias: `freenove_esp32s3_cam` |
| `custom` | mcu | supported | Supply DVP pins in `camera.pins` |

Linux camera publish is not supported yet.

## Base / kinematics (`base.type`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `diff_drive` | mcu, linux | supported | Differential drive + encoder odometry |
| `mecanum` | mcu, linux | planned | 4-channel; schema reserved |
| `ackermann` | mcu, linux | planned | Drive + steer; schema reserved |

## Network (`network.mode`)

MCU only (Linux uses the OS network stack; set `network.connect` for Zenoh):

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `softap` | mcu | supported | Solo SoftAP fallback (`rosie::softAP`) |
| `station` | mcu | supported | Join dedicated AP (`rosie::wifiStation`) |

## Bring your own driver

**MCU — use with DiffDriveStack:** contribute upstream (or vendor patch): driver
sources under `firmware/.../drivers/<category>/`, `registry.yaml` entry
(`status: supported`), `gen-config` macros in `robot_config.py`, and a
`DiffDriveStack` `#if` branch. See [Contributing](../../CONTRIBUTING.md).

**MCU — escape hatch:** implement `rosie::MotorDriver` (or the sensor API) in
your robot project and construct `MobileBase` yourself (skip `DiffDriveStack`).
See [Mobile base](mobile-base.md) and [BYOR](byor.md).

**Linux:** set `motors.driver: python` and `motors.class: mypkg:MyClass` where
the class implements `set_channels`, `stop`, and `close` (optional
`from_config` classmethod). Same pattern for `encoders` / `imu`. Built-in
drivers need `pip install "rosie-framework[linux]"`.

To contribute a chip upstream: add sources under
`firmware/include/rosie/drivers/<category>/` and `firmware/src/drivers/<category>/`
(categories: `motors`, `encoders`, `imu`, `camera`) or
`python/rosie/run/drivers/`, an entry in `registry.yaml` (with `platforms`),
codegen/stack wiring for MCU if needed, and a row on this page.
