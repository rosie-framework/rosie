"""TB6612FNG dual H-bridge via Pi GPIO PWM + direction pins (lgpio)."""

from __future__ import annotations

from typing import Any


class Tb6612MotorDriver:
    """Pins are BCM numbers. Channels map to left/right [-1, 1]."""

    def __init__(
        self,
        *,
        pwm_a: int,
        ain1: int,
        ain2: int,
        pwm_b: int,
        bin1: int,
        bin2: int,
        pwm_freq: int = 20000,
        pwm_min: float = 0.1,
        pwm_max: float = 1.0,
        chip: int = 0,
    ) -> None:
        from rosie.run.drivers import require_lgpio

        self._lgpio = require_lgpio()
        self._chip = self._lgpio.gpiochip_open(chip)
        self._pins = {
            "pwmA": pwm_a,
            "ain1": ain1,
            "ain2": ain2,
            "pwmB": pwm_b,
            "bin1": bin1,
            "bin2": bin2,
        }
        self._freq = int(pwm_freq)
        self._pwm_min = float(pwm_min)
        self._pwm_max = float(pwm_max)
        for name, pin in self._pins.items():
            if name.startswith("pwm"):
                self._lgpio.gpio_claim_output(self._chip, pin)
            else:
                self._lgpio.gpio_claim_output(self._chip, pin, 0)
        self.stop()

    @classmethod
    def from_config(cls, motors: dict[str, Any]) -> Tb6612MotorDriver:
        pins = motors.get("pins") or {}
        pwm = motors.get("pwm") or {}
        required = ("pwmA", "ain1", "ain2", "pwmB", "bin1", "bin2")
        missing = [k for k in required if k not in pins]
        if missing:
            raise ValueError(f"motors.pins missing keys: {missing}")
        pmin = float(pwm.get("min", 0.1))
        pmax = float(pwm.get("max", 1.0))
        return cls(
            pwm_a=int(pins["pwmA"]),
            ain1=int(pins["ain1"]),
            ain2=int(pins["ain2"]),
            pwm_b=int(pins["pwmB"]),
            bin1=int(pins["bin1"]),
            bin2=int(pins["bin2"]),
            pwm_freq=int(pwm.get("freq", 20000)),
            pwm_min=pmin,
            pwm_max=pmax,
            chip=int(motors.get("gpiochip", 0)),
        )

    def set_channels(self, channels: list[float]) -> None:
        left = float(channels[0]) if channels else 0.0
        right = float(channels[1]) if len(channels) > 1 else 0.0
        self._drive("pwmA", "ain1", "ain2", left)
        self._drive("pwmB", "bin1", "bin2", right)

    def _drive(self, pwm_key: str, in1: str, in2: str, value: float) -> None:
        value = max(-1.0, min(1.0, value))
        mag = abs(value)
        if mag < 1e-4:
            self._lgpio.gpio_write(self._chip, self._pins[in1], 0)
            self._lgpio.gpio_write(self._chip, self._pins[in2], 0)
            self._lgpio.tx_pwm(self._chip, self._pins[pwm_key], self._freq, 0.0)
            return
        duty = self._pwm_min + mag * (self._pwm_max - self._pwm_min)
        duty = max(0.0, min(100.0, duty * 100.0))  # lgpio duty is percent
        if value >= 0:
            self._lgpio.gpio_write(self._chip, self._pins[in1], 1)
            self._lgpio.gpio_write(self._chip, self._pins[in2], 0)
        else:
            self._lgpio.gpio_write(self._chip, self._pins[in1], 0)
            self._lgpio.gpio_write(self._chip, self._pins[in2], 1)
        self._lgpio.tx_pwm(self._chip, self._pins[pwm_key], self._freq, duty)

    def stop(self) -> None:
        self.set_channels([0.0, 0.0])

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._lgpio.gpiochip_close(self._chip)
        except Exception:
            pass
