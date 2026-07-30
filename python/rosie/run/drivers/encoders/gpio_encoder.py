"""Quadrature encoders via lgpio edge callbacks."""

from __future__ import annotations

import threading
from typing import Any


class GpioQuadratureEncoder:
    """Left/right A/B channels (BCM pins)."""

    def __init__(
        self,
        *,
        left: tuple[int, int],
        right: tuple[int, int],
        chip: int = 0,
    ) -> None:
        from rosie.run.drivers import require_lgpio

        self._lgpio = require_lgpio()
        self._chip = self._lgpio.gpiochip_open(chip)
        self._lock = threading.Lock()
        self._ticks = [0, 0]
        self._last = [0, 0]
        self._pins = [left[0], left[1], right[0], right[1]]
        for pin in self._pins:
            self._lgpio.gpio_claim_input(self._chip, pin)
            self._lgpio.gpio_claim_alert(self._chip, pin, self._lgpio.BOTH_EDGES)
        self._cb_ids = []
        for i, pin in enumerate(self._pins):
            side = 0 if i < 2 else 1
            is_a = i % 2 == 0
            cid = self._lgpio.callback(
                self._chip, pin, self._lgpio.BOTH_EDGES, self._make_cb(side, is_a)
            )
            self._cb_ids.append(cid)

    def _make_cb(self, side: int, is_a: bool):
        def _cb(chip: int, gpio: int, level: int, timestamp: int) -> None:
            # Simple count: increment on A rising when B is low, else decrement.
            with self._lock:
                a_pin = self._pins[side * 2]
                b_pin = self._pins[side * 2 + 1]
                try:
                    a = self._lgpio.gpio_read(self._chip, a_pin)
                    b = self._lgpio.gpio_read(self._chip, b_pin)
                except Exception:
                    return
                if is_a and level == 1:
                    self._ticks[side] += 1 if b == 0 else -1
                elif (not is_a) and level == 1:
                    self._ticks[side] += 1 if a == 1 else -1

        return _cb

    @classmethod
    def from_config(cls, enc: dict[str, Any]) -> GpioQuadratureEncoder:
        pins = enc.get("pins") or {}
        left = pins.get("left") or [0, 0]
        right = pins.get("right") or [0, 0]
        if len(left) < 2 or len(right) < 2:
            raise ValueError("encoders.pins.left/right need [A, B] pin pairs")
        return cls(
            left=(int(left[0]), int(left[1])),
            right=(int(right[0]), int(right[1])),
            chip=int(enc.get("gpiochip", 0)),
        )

    def read_ticks(self) -> tuple[int, int]:
        with self._lock:
            return int(self._ticks[0]), int(self._ticks[1])

    def zero(self) -> None:
        """Clear cumulative tick counters (pose zero hook)."""
        with self._lock:
            self._ticks = [0, 0]
            self._last = [0, 0]

    def close(self) -> None:
        for cid in self._cb_ids:
            try:
                cid.cancel()
            except Exception:
                pass
        try:
            self._lgpio.gpiochip_close(self._chip)
        except Exception:
            pass
