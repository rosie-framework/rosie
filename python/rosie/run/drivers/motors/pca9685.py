"""PCA9685 I2C PWM HAT motor channels (smbus2)."""

from __future__ import annotations

from typing import Any


class Pca9685MotorDriver:
    """Two channels on a PCA9685 (left/right duty, direction via sign)."""

    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(
        self,
        *,
        bus: int = 1,
        addr: int = 0x40,
        left_ch: int = 0,
        right_ch: int = 1,
        pwm_freq: int = 1000,
        pwm_min: float = 0.1,
        pwm_max: float = 1.0,
    ) -> None:
        from rosie.run.drivers import require_smbus2

        smbus2 = require_smbus2()
        self._bus = smbus2.SMBus(bus)
        self._addr = int(addr)
        self._left = int(left_ch)
        self._right = int(right_ch)
        self._pwm_min = float(pwm_min)
        self._pwm_max = float(pwm_max)
        self._set_pwm_freq(int(pwm_freq))
        self.stop()

    @classmethod
    def from_config(cls, motors: dict[str, Any]) -> Pca9685MotorDriver:
        i2c = motors.get("i2c") or {}
        channels = motors.get("channels") or {}
        pwm = motors.get("pwm") or {}
        pmin = float(pwm.get("min", 0.1))
        pmax = float(pwm.get("max", 1.0))
        if pmax > 1.0:
            pmin /= 100.0
            pmax /= 100.0
        return cls(
            bus=int(i2c.get("bus", 1)),
            addr=int(i2c.get("addr", 0x40)),
            left_ch=int(channels.get("left", 0)),
            right_ch=int(channels.get("right", 1)),
            pwm_freq=int(pwm.get("freq", 1000)),
            pwm_min=pmin,
            pwm_max=pmax,
        )

    def _write8(self, reg: int, value: int) -> None:
        self._bus.write_byte_data(self._addr, reg, value & 0xFF)

    def _set_pwm_freq(self, freq_hz: int) -> None:
        import time

        prescale = int(25000000.0 / (4096.0 * freq_hz) - 1.0)
        old = self._bus.read_byte_data(self._addr, self.MODE1)
        self._write8(self.MODE1, (old & 0x7F) | 0x10)  # sleep
        self._write8(self.PRESCALE, prescale)
        self._write8(self.MODE1, old)
        time.sleep(0.005)
        self._write8(self.MODE1, old | 0xA1)  # auto-increment + restart

    def _set_channel(self, channel: int, duty: float) -> None:
        duty = max(0.0, min(1.0, duty))
        ticks = int(duty * 4095)
        base = self.LED0_ON_L + 4 * channel
        self._bus.write_i2c_block_data(
            self._addr,
            base,
            [0, 0, ticks & 0xFF, (ticks >> 8) & 0xFF],
        )

    def set_channels(self, channels: list[float]) -> None:
        # Unsigned PWM only: magnitude. Sign is lost without dir pins;
        # treat negative as zero magnitude for HAT-only setups (document).
        for ch, val in ((self._left, channels[0] if channels else 0.0),
                        (self._right, channels[1] if len(channels) > 1 else 0.0)):
            mag = abs(float(val))
            if mag < 1e-4:
                self._set_channel(ch, 0.0)
            else:
                duty = self._pwm_min + mag * (self._pwm_max - self._pwm_min)
                self._set_channel(ch, duty)

    def stop(self) -> None:
        self.set_channels([0.0, 0.0])

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._bus.close()
        except Exception:
            pass
