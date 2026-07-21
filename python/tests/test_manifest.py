"""Unit tests for fleet manifest parsing (no Zenoh router required)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rosie.manifest import FleetManifest, load_manifest, manifest_from_dict


class ManifestTests(unittest.TestCase):
    def test_from_dict_minimal(self) -> None:
        m = manifest_from_dict({"fleet": "lab", "robots": ["car1", "car2"]})
        self.assertEqual(m.fleet, "lab")
        self.assertEqual(m.robot_ids(), ["car1", "car2"])
        self.assertIsNone(m.required_status("car1"))

    def test_from_dict_rich(self) -> None:
        m = manifest_from_dict(
            {
                "fleet": "lab",
                "connect": "tcp/1.2.3.4:7447",
                "defaults": {"v_max": 0.2},
                "robots": [
                    {"id": "car1", "kind": "esp32-car", "status": "ready"},
                    {"robot_id": "car2", "type": "pi-car"},
                ],
            }
        )
        self.assertEqual(m.connect, "tcp/1.2.3.4:7447")
        self.assertEqual(m.defaults["v_max"], 0.2)
        self.assertEqual(m.robots[0].kind, "esp32-car")
        self.assertEqual(m.required_status("car1"), "ready")
        self.assertIsNone(m.required_status("car2"))
        self.assertEqual(m.robots[1].kind, "pi-car")

    def test_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            manifest_from_dict({"fleet": "lab", "robots": ["a", "a"]})

    def test_load_json_file(self) -> None:
        payload = {"fleet": "demo", "robots": [{"id": "r1"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fleet.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            m = load_manifest(path)
            self.assertIsInstance(m, FleetManifest)
            self.assertEqual(m.fleet, "demo")
            self.assertEqual(m.robot_ids(), ["r1"])


if __name__ == "__main__":
    unittest.main()
