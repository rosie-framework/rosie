"""MPU6050 accel + gyro reader over I2C (smbus2)."""

from __future__ import annotations

import math
import struct
from typing import Any

# Register map (subset)
_PWR_MGMT_1 = 0x6B
_ACCEL_XOUT_H = 0x3B
# Default full-scale after reset: accel ±2 g, gyro ±250 deg/s
_ACCEL_LSB_PER_G = 16384.0
_GYRO_LSB_PER_DPS = 131.0
_G = 9.80665


class Mpu6050Imu:
    def __init__(self, *, bus: int = 1, addr: int = 0x68) -> None:
        from rosie.run.drivers import require_smbus2

        smbus2 = require_smbus2()
        self._bus = smbus2.SMBus(bus)
        self._addr = int(addr)
        # Wake device
        self._bus.write_byte_data(self._addr, _PWR_MGMT_1, 0)

    @classmethod
    def from_config(cls, imu: dict[str, Any]) -> Mpu6050Imu:
        i2c = imu.get("i2c") or {}
        return cls(bus=int(i2c.get("bus", 1)), addr=int(i2c.get("addr", 0x68)))

    def read_sample(self) -> tuple[float, float, float, float, float, float] | None:
        """Return ``(ax, ay, az, gx, gy, gz)`` in m/s² and rad/s, or None."""
        try:
            data = self._bus.read_i2c_block_data(self._addr, _ACCEL_XOUT_H, 14)
            ax_i, ay_i, az_i, _temp, gx_i, gy_i, gz_i = struct.unpack(">hhhhhhh", bytes(data))
            ax = (ax_i / _ACCEL_LSB_PER_G) * _G
            ay = (ay_i / _ACCEL_LSB_PER_G) * _G
            az = (az_i / _ACCEL_LSB_PER_G) * _G
            scale = math.pi / 180.0 / _GYRO_LSB_PER_DPS
            return (ax, ay, az, gx_i * scale, gy_i * scale, gz_i * scale)
        except Exception:
            return None

    def read_yaw_rate(self) -> float | None:
        sample = self.read_sample()
        if sample is None:
            return None
        return sample[5]  # gyro_z

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
