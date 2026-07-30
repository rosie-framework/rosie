"""Median-of-N ring buffer for range samples (matches firmware MedianWindow)."""

from __future__ import annotations

from rosie.robot_config import RANGE_MEDIAN_WINDOW


class MedianWindow:
    """Fixed-window median; failed reads should not call ``push``."""

    def __init__(self, n: int = RANGE_MEDIAN_WINDOW) -> None:
        self._n = max(1, int(n))
        self._buf: list[float] = []

    def clear(self) -> None:
        self._buf.clear()

    def push(self, sample: float) -> float:
        self._buf.append(float(sample))
        if len(self._buf) > self._n:
            self._buf.pop(0)
        return self.median()

    def median(self) -> float:
        if not self._buf:
            return 0.0
        s = sorted(self._buf)
        return s[len(s) // 2]

    def __len__(self) -> int:
        return len(self._buf)
