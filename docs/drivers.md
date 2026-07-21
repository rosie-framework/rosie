# Drivers & inventory

Catalog of `robot.yaml` type strings. Same data as `firmware/drivers/registry.yaml`
and `rosie drivers list`.

## Motors (`motors.driver`)

| id | status | notes |
|----|--------|-------|
| `tb6612` | supported | TB6612FNG dual H-bridge (2 channels) |
| `l298n` | planned | BYO via `MotorDriver` until supported |
| `drv8833` | planned | BYO via `MotorDriver` until supported |

## Encoders

| id | status | notes |
|----|--------|-------|
| `quad_encoder` | supported | Quadrature A/B via ESP32Encoder (`encoders.pins`) |

## IMU (`imu.chip`)

| id | status | notes |
|----|--------|-------|
| `mpu6050` | supported | Gyro yaw-rate for odometry fusion |

## Camera (`camera.board`)

| id | status | notes |
|----|--------|-------|
| `esp32s3_eye` | supported | ESP32-S3-EYE DVP pinout (also Freenove ESP32-S3 CAM clones). Alias: `freenove_esp32s3_cam` |
| `custom` | — | Supply explicit pins in YAML (escape hatch) |

## Base / kinematics (`base.type`)

| id | status | notes |
|----|--------|-------|
| `diff_drive` | supported | Differential drive + encoder odometry |
| `mecanum` | planned | 4-channel; schema reserved |
| `ackermann` | planned | Drive + steer; schema reserved |

## Network (`network.mode`)

| id | status | notes |
|----|--------|-------|
| `softap` | supported | Solo SoftAP fallback (`rosie::softAP`) |
| `station` | supported | Join dedicated AP (`rosie::wifiStation`) |

## Bring your own driver

If a chip is missing or `planned`, implement `rosie::MotorDriver` (or the sensor
API) in your robot project and construct `MobileBase` yourself (skip
`DiffDriveStack`). See [Mobile base](mobile-base.md) and [BYOR](byor.md).

To contribute a chip upstream: add sources under `firmware/`, an entry in
`registry.yaml`, and a row on this page.
