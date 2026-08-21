"""Unit tests for MobileRobot relative odom helpers (no Zenoh)."""

from __future__ import annotations

import math
import unittest

from rosie.mobile_robot import MobileRobot, _wrap_deg


class TestWrapDeg(unittest.TestCase):
    def test_identity(self) -> None:
        self.assertAlmostEqual(_wrap_deg(0.0), 0.0)
        self.assertAlmostEqual(_wrap_deg(45.0), 45.0)
        self.assertAlmostEqual(_wrap_deg(-90.0), -90.0)

    def test_wrap_across_360(self) -> None:
        self.assertAlmostEqual(_wrap_deg(190.0), -170.0)
        self.assertAlmostEqual(_wrap_deg(-190.0), 170.0)
        self.assertAlmostEqual(_wrap_deg(350.0 - 10.0), -20.0)

    def test_heading_prefers_heading_deg(self) -> None:
        self.assertAlmostEqual(
            MobileRobot._heading_deg({"heading_deg": 90.0, "theta": 0.0}),
            90.0,
        )

    def test_heading_falls_back_to_theta(self) -> None:
        self.assertAlmostEqual(
            MobileRobot._heading_deg({"theta": math.pi / 2}),
            90.0,
        )


if __name__ == "__main__":
    unittest.main()
