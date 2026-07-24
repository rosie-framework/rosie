# Drivers & inventory

Catalog of `robot.yaml` type strings. Same data as `firmware/drivers/registry.yaml`
and `rosie drivers list`. Entries are tagged with **platforms** (`mcu`, `linux`,
or both).

```bash
rosie drivers list
rosie drivers list --platform linux
rosie drivers list --category motors --platform mcu
```

## Motors (`motors.driver`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `tb6612` | mcu, linux | supported | TB6612FNG dual H-bridge (2 channels); MCU GPIO or Pi BCM |
| `pca9685` | linux | supported | I2C PWM HAT (magnitude PWM) |
| `python` | linux | supported | BYO `MotorDriver` via `motors.class` |
| `l298n` | mcu | planned | BYO via `MotorDriver` until supported |
| `drv8833` | mcu | planned | BYO via `MotorDriver` until supported |

## Encoders

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `quad_encoder` | mcu | supported | Quadrature A/B via ESP32Encoder (`encoders.pins`) |
| `gpio_quadrature` | linux | supported | Quadrature A/B via Pi GPIO (`lgpio`) |
| `python` | linux | supported | BYO `EncoderReader` via `encoders.class` |

On Linux, omit `encoders` to use dead-reckoning odometry (commanded twist,
optional IMU yaw).

## IMU (`imu.chip`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `mpu6050` | mcu, linux | supported | Gyro yaw-rate for odometry fusion |
| `python` | linux | supported | BYO `ImuReader` via `imu.class` |

## Camera (`camera.board`)

| id | platforms | status | notes |
|----|-----------|--------|-------|
| `esp32s3_eye` | mcu | supported | ESP32-S3-EYE DVP pinout (also Freenove ESP32-S3 CAM clones). Alias: `freenove_esp32s3_cam` |
| `custom` | mcu | — | Supply explicit pins in YAML (escape hatch) |

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

**MCU:** implement `rosie::MotorDriver` (or the sensor API) in your robot project
and construct `MobileBase` yourself (skip `DiffDriveStack`). See
[Mobile base](mobile-base.md) and [BYOR](byor.md).

**Linux:** set `motors.driver: python` and `motors.class: mypkg:MyClass` where
the class implements `set_channels`, `stop`, and `close` (optional
`from_config` classmethod). Same pattern for `encoders` / `imu`. Built-in
drivers need `pip install "rosie-framework[linux]"`.

To contribute a chip upstream: add sources under `firmware/` or
`python/rosie/run/drivers/`, an entry in `registry.yaml` (with `platforms`),
and a row on this page.
