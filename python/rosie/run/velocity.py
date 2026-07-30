"""Inner-loop wheel velocity controller (mirrors firmware VelocityController)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class VelocityGains:
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    i_clamp: float = 0.5


@runtime_checkable
class VelocityController(Protocol):
    """Feedforward channels + closed-loop correction from per-wheel velocity error.

    Zero gains ⇒ out == clamp(ff) (open-loop passthrough).
    """

    def configure(self, gains: VelocityGains) -> None: ...

    def gains(self) -> VelocityGains: ...

    def update(
        self,
        ff: list[float],
        target: list[float] | None,
        meas: list[float] | None,
        dt: float,
    ) -> list[float]: ...

    def reset(self) -> None: ...


class PidVelocityController:
    """Per-wheel PID on velocity error, added to feedforward.

    Numerics match ``firmware/src/velocity_controller.cpp`` exactly.
    """

    MAX_CHANNELS = 4

    def __init__(self, gains: VelocityGains | None = None) -> None:
        self._gains = gains or VelocityGains()
        self._integ = [0.0] * self.MAX_CHANNELS
        self._prev_err = [0.0] * self.MAX_CHANNELS
        self._have_prev = [False] * self.MAX_CHANNELS

    def configure(self, gains: VelocityGains) -> None:
        self._gains = VelocityGains(
            kp=float(gains.kp),
            ki=float(gains.ki),
            kd=float(gains.kd),
            i_clamp=float(gains.i_clamp),
        )
        self.reset()

    def gains(self) -> VelocityGains:
        return VelocityGains(
            kp=self._gains.kp,
            ki=self._gains.ki,
            kd=self._gains.kd,
            i_clamp=self._gains.i_clamp,
        )

    def reset(self) -> None:
        for i in range(self.MAX_CHANNELS):
            self._integ[i] = 0.0
            self._prev_err[i] = 0.0
            self._have_prev[i] = False

    def update(
        self,
        ff: list[float],
        target: list[float] | None,
        meas: list[float] | None,
        dt: float,
    ) -> list[float]:
        n = min(len(ff), self.MAX_CHANNELS)
        if dt <= 0.0 or dt > 0.2:
            dt = 0.02

        closed = (
            self._gains.kp != 0.0
            or self._gains.ki != 0.0
            or self._gains.kd != 0.0
        )
        out: list[float] = []
        for i in range(n):
            u = float(ff[i])
            if closed and target is not None and meas is not None and i < len(target) and i < len(meas):
                err = float(target[i]) - float(meas[i])
                self._integ[i] += err * dt
                ic = self._gains.i_clamp
                if ic < 0.0:
                    ic = 0.0
                if self._integ[i] > ic:
                    self._integ[i] = ic
                if self._integ[i] < -ic:
                    self._integ[i] = -ic

                deriv = 0.0
                if self._have_prev[i]:
                    deriv = (err - self._prev_err[i]) / dt
                self._prev_err[i] = err
                self._have_prev[i] = True

                u += (
                    self._gains.kp * err
                    + self._gains.ki * self._integ[i]
                    + self._gains.kd * deriv
                )
            if u > 1.0:
                u = 1.0
            if u < -1.0:
                u = -1.0
            out.append(u)
        return out
