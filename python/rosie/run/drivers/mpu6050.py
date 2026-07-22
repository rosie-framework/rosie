"""MPU6050 yaw-rate reader over I2C (smbus2)."""

from __future__ import annotations

import struct
from typing import Any

# Register map (subset)
_PWR_MGMT_1 = 0x6B
_GYRO_ZOUT_H = 0x47
# ±250 deg/s → 131 LSB/(deg/s)
_GYRO_SCALE = 131.0


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

    def read_yaw_rate(self) -> float | None:
        try:
            data = self._bus.read_i2c_block_data(self._addr, _GYRO_ZOUT_H, 2)
            raw = struct.unpack(">h", bytes(data))[0]
            # deg/s → rad/s
            import math

            return (raw / _GYRO_SCALE) * math.pi / 180.0
        except Exception:
            return None

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
