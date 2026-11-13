"""Tests for connect: auto, client-mode config, and fleet-verified discovery."""

from __future__ import annotations

import pytest

from rosie.connect import (
    AUTO_CONNECT,
    DEFAULT_CONNECT,
    is_auto_connect,
    resolve_connect,
    zenoh_config_pairs,
)
from rosie.discovery import (
    ScoutedRouter,
    parse_router_announcement,
    resolve_auto_connect,
    router_announcement,
)


def test_is_auto_connect():
    assert is_auto_connect("auto")
    assert is_auto_connect("AUTO")
    assert is_auto_connect("scout")
    assert not is_auto_connect(None)
    assert not is_auto_connect(DEFAULT_CONNECT)
    assert not is_auto_connect("tcp/192.168.4.2:7447")


def test_resolve_connect_preserves_auto(monkeypatch):
    monkeypatch.delenv("ROSIE_CONNECT", raising=False)
    assert resolve_connect(None) == DEFAULT_CONNECT
    assert resolve_connect("auto") == "auto"
    monkeypatch.setenv("ROSIE_CONNECT", "auto")
    assert resolve_connect(None) == "auto"


def test_zenoh_config_pairs_explicit_is_client_no_scout():
    pairs = dict(zenoh_config_pairs("tcp/192.168.8.2:7447"))
    assert pairs["mode"] == '"client"'
    assert pairs["connect/endpoints"] == '["tcp/192.168.8.2:7447"]'
    assert pairs["scouting/multicast/enabled"] == "false"


def test_zenoh_config_pairs_auto_scouts():
    pairs = dict(zenoh_config_pairs("auto"))
    assert pairs["mode"] == '"client"'
    assert "connect/endpoints" not in pairs
    assert pairs["scouting/multicast/enabled"] == "true"


def test_router_announcement_shape():
    payload = router_announcement(
        "lab",
        locators=["tcp/127.0.0.1:7447", "tcp/192.168.8.2:7447"],
        secure=True,
        started=1.0,
    )
    parsed = parse_router_announcement(payload)
    assert parsed is not None
    assert parsed["fleet_id"] == "lab"
    assert parsed["secure"] is True
    assert parsed["kind"] == "router"
    assert "tcp/192.168.8.2:7447" in parsed["locators"]


def test_resolve_auto_accepts_matching_fleet():
    hellos = [
        ScoutedRouter(zid="a", whatami="router", locators=["tcp/1.1.1.1:7447"]),
        ScoutedRouter(zid="b", whatami="router", locators=["tcp/2.2.2.2:7447"]),
    ]

    def verify(loc: str, fleet: str):
        if loc == "tcp/1.1.1.1:7447":
            return {"fleet_id": "other"}
        if loc == "tcp/2.2.2.2:7447":
            return {"fleet_id": fleet, "locators": [loc]}
        return None

    chosen = resolve_auto_connect(
        "lab",
        scout_fn=lambda: hellos,
        verify_fn=verify,
    )
    assert chosen == "tcp/2.2.2.2:7447"


def test_resolve_auto_rejects_all_and_lists_candidates():
    hellos = [ScoutedRouter(zid="a", locators=["tcp/1.1.1.1:7447"])]

    def verify(loc: str, fleet: str):
        return {"fleet_id": "other"}

    with pytest.raises(RuntimeError, match="tcp/1.1.1.1:7447→other"):
        resolve_auto_connect("lab", scout_fn=lambda: hellos, verify_fn=verify)


def test_resolve_auto_timeout_unknown():
    hellos = [ScoutedRouter(zid="a", locators=["tcp/1.1.1.1:7447"])]

    def verify(loc: str, fleet: str):
        return None

    with pytest.raises(RuntimeError, match="unknown"):
        resolve_auto_connect("lab", scout_fn=lambda: hellos, verify_fn=verify)


def test_resolve_auto_tries_explicit_first():
    seen: list[str] = []

    def verify(loc: str, fleet: str):
        seen.append(loc)
        if loc == "tcp/9.9.9.9:7447":
            return {"fleet_id": fleet}
        return {"fleet_id": "nope"}

    chosen = resolve_auto_connect(
        "lab",
        extra="tcp/9.9.9.9:7447",
        scout_fn=lambda: [
            ScoutedRouter(zid="a", locators=["tcp/1.1.1.1:7447"]),
        ],
        verify_fn=verify,
    )
    assert chosen == "tcp/9.9.9.9:7447"
    assert seen[0] == "tcp/9.9.9.9:7447"


def test_robot_setup_writes_bridge_namespace(tmp_path, monkeypatch):
    import json
    from argparse import Namespace

    from rosie.cli.robot import cmd_setup

    monkeypatch.chdir(tmp_path)
    code = cmd_setup(
        Namespace(
            fleet="lab",
            robot="bot1",
            profile="rosmaster_x3",
            connect="tcp/10.0.0.8:7447",
            mode="client",
            config=None,
            secure=False,
            triple=None,
            no_download=True,
            bridge="zenoh-bridge-ros2dds",
        )
    )
    assert code == 0
    cfg = json.loads((tmp_path / "rosie-bridge.json5").read_text(encoding="utf-8"))
    assert cfg["plugins"]["ros2dds"]["namespace"] == "/lab/bot1"
    assert cfg["rosie"]["connect"] == "tcp/10.0.0.8:7447"
    assert cfg["mode"] == "client"


def test_service_exec_sources_profile_distro():
    from rosie.cli.robot import service_exec

    line = service_exec("humble", ["rosie", "robot", "watchdog", "--fleet", "lab"])
    assert line.startswith("/bin/bash -lc ")
    assert "source /opt/ros/humble/setup.bash" in line
    assert "rosie robot watchdog --fleet lab" in line
