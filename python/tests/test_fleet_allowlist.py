"""Fleet allowlist filtering on Fleet.robots / topics (no live Zenoh)."""

from __future__ import annotations

import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from rosie.fleet import Fleet
from rosie.fleet_msgs import RobotPresence


class FakeFleetPresence(unittest.TestCase):
    def test_robots_filters_allowlist(self) -> None:
        # Bypass Zenoh open by constructing a bare object
        f = object.__new__(Fleet)
        f.fleet = "lab"
        f.allowlist = {"car1"}
        f._lock = __import__("threading").Lock()
        f._presence = {
            "car1": (1e18, RobotPresence(robot_id="car1", status="ready")),
            "intruder": (1e18, RobotPresence(robot_id="intruder", status="ready")),
        }
        f._presence_sub = object()  # skip subscribe
        f._ensure_presence_sub = lambda: None  # type: ignore[method-assign]

        with mock.patch("rosie.fleet.time.sleep", return_value=None):
            with mock.patch("rosie.fleet.time.time", return_value=1e18):
                listed = f.robots(ttl_s=3.0, wait_s=0.0)
                all_listed = f.robots(ttl_s=3.0, wait_s=0.0, include_all=True)
                ignored = f.ignored_robots(ttl_s=3.0, wait_s=0.0)

        self.assertEqual([r.robot_id for r in listed], ["car1"])
        self.assertEqual(sorted(r.robot_id for r in all_listed), ["car1", "intruder"])
        self.assertEqual([r.robot_id for r in ignored], ["intruder"])

    def test_open_mode_no_allowlist(self) -> None:
        f = object.__new__(Fleet)
        f.fleet = "lab"
        f.allowlist = None
        f._lock = __import__("threading").Lock()
        f._presence = {
            "car1": (1e18, RobotPresence(robot_id="car1", status="ready")),
            "intruder": (1e18, RobotPresence(robot_id="intruder", status="ready")),
        }
        f._presence_sub = object()
        f._ensure_presence_sub = lambda: None  # type: ignore[method-assign]

        with mock.patch("rosie.fleet.time.sleep", return_value=None):
            with mock.patch("rosie.fleet.time.time", return_value=1e18):
                listed = f.robots(ttl_s=3.0, wait_s=0.0)

        self.assertEqual(sorted(r.robot_id for r in listed), ["car1", "intruder"])


class FleetKwargsSecureGate(unittest.TestCase):
    def test_allowlist_requires_secure_flag(self) -> None:
        from rosie.cli.fleet import _fleet_kwargs
        from rosie.manifest import FleetManifest, RobotSpec

        manifest = FleetManifest(
            fleet="lab",
            robots=(RobotSpec(id="car1"), RobotSpec(id="car2")),
            path=Path("/tmp/m.yaml"),
        )
        with mock.patch("rosie.manifest.resolve_manifest", return_value=manifest):
            open_kw = _fleet_kwargs(
                Namespace(
                    secure=False, all=False, manifest=None, fleet="lab", connect=None
                )
            )
            secure_kw = _fleet_kwargs(
                Namespace(
                    secure=True, all=False, manifest=None, fleet="lab", connect=None
                )
            )
        self.assertIsNone(open_kw["allowlist"])
        self.assertEqual(secure_kw["allowlist"], {"car1", "car2"})


if __name__ == "__main__":
    unittest.main()
