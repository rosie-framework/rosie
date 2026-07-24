"""Unit tests for fleet manifest, enrollment, and auth helpers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rosie.auth import (
    bus_mode,
    credentials_for,
    resolve_secret_plaintext,
    sha256_hex,
    sync_secret_into_robot_yaml,
    write_router_auth_files,
)
from rosie.fleet_home import generate_secret, write_secret_file
from rosie.manifest import (
    FleetManifest,
    RobotSpec,
    add_robot,
    load_manifest,
    manifest_from_dict,
    remove_robot,
    resolve_manifest_path,
    save_manifest,
)


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
                "secret_file": "/tmp/lab.secret",
                "robots": [
                    {"id": "car1", "kind": "esp32-car", "status": "ready"},
                    {"robot_id": "car2", "type": "pi-car"},
                ],
            }
        )
        self.assertEqual(m.connect, "tcp/1.2.3.4:7447")
        self.assertEqual(m.secret_file, "/tmp/lab.secret")
        self.assertEqual(m.defaults["v_max"], 0.2)
        self.assertEqual(m.robots[0].kind, "esp32-car")
        self.assertEqual(m.required_status("car1"), "ready")
        self.assertIsNone(m.required_status("car2"))
        self.assertEqual(m.robots[1].kind, "pi-car")

    def test_empty_robots_allowed(self) -> None:
        m = manifest_from_dict(
            {"fleet": "lab", "robots": []},
            allow_empty_robots=True,
        )
        self.assertEqual(m.robot_ids(), [])

    def test_empty_robots_rejected_by_default(self) -> None:
        with self.assertRaises(ValueError):
            manifest_from_dict({"fleet": "lab", "robots": []})

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

    def test_add_remove_roundtrip(self) -> None:
        m = FleetManifest(fleet="lab", robots=())
        m = add_robot(m, RobotSpec(id="car1", kind="esp32-car"))
        self.assertEqual(m.robot_ids(), ["car1"])
        with self.assertRaises(ValueError):
            add_robot(m, "car1")
        m = remove_robot(m, "car1")
        self.assertEqual(m.robot_ids(), [])
        with self.assertRaises(ValueError):
            remove_robot(m, "car1")

    def test_save_and_load_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.yaml"
            m = FleetManifest(
                fleet="lab",
                robots=(RobotSpec(id="car1", kind="esp32-car", status="ready"),),
            )
            save_manifest(m, path)
            loaded = load_manifest(path, allow_empty_robots=True)
            self.assertEqual(loaded.fleet, "lab")
            self.assertEqual(loaded.robots[0].kind, "esp32-car")
            self.assertEqual(loaded.required_status("car1"), "ready")

    def test_resolve_manifest_path_fleet(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            # Clear ROSIE_FLEET_MANIFEST if set in environment
            os.environ.pop("ROSIE_FLEET_MANIFEST", None)
            os.environ.pop("ROSIE_FLEET", None)
            p = resolve_manifest_path(fleet="lab")
            self.assertIsNotNone(p)
            assert p is not None
            self.assertTrue(str(p).endswith(os.path.join("fleets", "lab", "manifest.yaml")))


class AuthTests(unittest.TestCase):
    def test_sha256_hex(self) -> None:
        # UTF-8 of "clientpassword" with no trailing newline
        self.assertEqual(
            sha256_hex("clientpassword"),
            "857c5c62c9127966b5c58c694e79e70d3e3941eb4b435000b14a2a19fb5593f9",
        )

    def test_bus_mode(self) -> None:
        self.assertEqual(bus_mode(fleet=None, secure=False), "solo-open")
        self.assertEqual(bus_mode(fleet=None, secure=True), "solo-secure")
        self.assertEqual(bus_mode(fleet="lab", secure=False), "fleet-open")
        self.assertEqual(bus_mode(fleet="lab", secure=True), "fleet-secure")

    def test_resolve_secret_gated_by_secure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            secret_path = Path(tmp) / "secret"
            write_secret_file(secret_path, "leftover-secret")
            with mock.patch(
                "rosie.auth.default_secret_path", return_value=secret_path
            ):
                self.assertIsNone(
                    resolve_secret_plaintext(fleet="lab", secure=False)
                )
                self.assertEqual(
                    resolve_secret_plaintext(fleet="lab", secure=True),
                    "leftover-secret",
                )

    def test_resolve_secret_explicit_without_secure(self) -> None:
        self.assertEqual(
            resolve_secret_plaintext(secret="one-shot", secure=False),
            "one-shot",
        )

    def test_resolve_solo_secret_not_implicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            solo = Path(tmp) / "solo-secret"
            write_secret_file(solo, "solo-leftover")
            with mock.patch("rosie.auth.solo_secret_path", return_value=solo):
                self.assertIsNone(resolve_secret_plaintext(secure=False))
                self.assertEqual(
                    resolve_secret_plaintext(secure=True), "solo-leftover"
                )

    def test_credentials_for_fleet_and_solo(self) -> None:
        c = credentials_for(fleet="lab", password="s3cret")
        assert c is not None
        self.assertEqual(c.user, "lab")
        self.assertEqual(c.password, "s3cret")
        c2 = credentials_for(fleet=None, password="s3cret")
        assert c2 is not None
        self.assertEqual(c2.user, "rosie")

    def test_write_router_auth_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg, dictionary = write_router_auth_files(
                fleet="lab",
                password="s3cret",
                out_dir=Path(tmp),
            )
            self.assertTrue(cfg.is_file())
            self.assertTrue(dictionary.is_file())
            text = dictionary.read_text(encoding="utf-8")
            self.assertIn("lab:", text)
            self.assertIn(sha256_hex("s3cret"), text)
            conf = cfg.read_text(encoding="utf-8")
            self.assertIn("usrpwd", conf)
            self.assertIn("dictionary_file", conf)

    def test_sync_secret_into_robot_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "robot.yaml"
            path.write_text(
                "robot: car1\nfleet: lab\nnetwork:\n  mode: station\n  connect: tcp/1.2.3.4:7447\n",
                encoding="utf-8",
            )
            changed = sync_secret_into_robot_yaml(path, password="abc", user="lab")
            self.assertTrue(changed)
            text = path.read_text(encoding="utf-8")
            self.assertIn("fleet_secret: abc", text)
            self.assertIn("user: lab", text)
            changed2 = sync_secret_into_robot_yaml(path, password="abc", user="lab")
            self.assertFalse(changed2)

    def test_generate_and_write_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            s = generate_secret()
            write_secret_file(path, s)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), s)


class RouterModeTests(unittest.TestCase):
    def test_resolve_router_auth_open_ignores_file(self) -> None:
        from rosie.cli.router import resolve_router_auth

        with tempfile.TemporaryDirectory() as tmp:
            secret_path = Path(tmp) / "secret"
            write_secret_file(secret_path, "leftover")
            with mock.patch(
                "rosie.auth.default_secret_path", return_value=secret_path
            ):
                self.assertIsNone(
                    resolve_router_auth(
                        secure=False,
                        fleet="lab",
                        secret=None,
                        secret_file=None,
                        manifest_secret_file=None,
                    )
                )
                self.assertEqual(
                    resolve_router_auth(
                        secure=True,
                        fleet="lab",
                        secret=None,
                        secret_file=None,
                        manifest_secret_file=None,
                    ),
                    "leftover",
                )

    def test_resolve_router_auth_explicit_secret(self) -> None:
        from rosie.cli.router import resolve_router_auth

        self.assertEqual(
            resolve_router_auth(
                secure=False,
                fleet="lab",
                secret="cli-secret",
                secret_file=None,
                manifest_secret_file=None,
            ),
            "cli-secret",
        )


class AllowlistUnitTests(unittest.TestCase):
    def test_allowed_ids(self) -> None:
        m = manifest_from_dict({"fleet": "lab", "robots": ["a", "b"]})
        self.assertEqual(m.allowed_ids(), {"a", "b"})

    def test_fleet_kwargs_allowlist_only_when_secure(self) -> None:
        from argparse import Namespace

        from rosie.cli.fleet import _fleet_kwargs
        from rosie.manifest import FleetManifest, RobotSpec

        manifest = FleetManifest(
            fleet="lab",
            robots=(RobotSpec(id="car1"),),
            path=Path("/tmp/manifest.yaml"),
        )
        with mock.patch(
            "rosie.manifest.resolve_manifest", return_value=manifest
        ):
            open_kw = _fleet_kwargs(
                Namespace(secure=False, all=False, manifest=None, fleet="lab", connect=None)
            )
            secure_kw = _fleet_kwargs(
                Namespace(secure=True, all=False, manifest=None, fleet="lab", connect=None)
            )
            all_kw = _fleet_kwargs(
                Namespace(secure=True, all=True, manifest=None, fleet="lab", connect=None)
            )
        self.assertIsNone(open_kw["allowlist"])
        self.assertFalse(open_kw["secure"])
        self.assertEqual(secure_kw["allowlist"], {"car1"})
        self.assertTrue(secure_kw["secure"])
        self.assertIsNone(all_kw["allowlist"])


if __name__ == "__main__":
    unittest.main()
