"""Tests for connect: auto, client-mode config, and fleet-verified discovery."""

from __future__ import annotations

import pytest

from rosie.connect import (
    AUTO_CONNECT,
    DEFAULT_CONNECT,
    SOFTAP_CONNECT,
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
from rosie.robot_config import (
    RobotConfig,
    generate_robot_config_h,
    requested_connect,
    resolve_robot_connect,
    validate_robot_config,
)


def _mcu(**network):
    raw = {
        "robot": "testbot",
        "fleet": "lab",
        "network": {"mode": "softap", "ssid": "x", "password": "y", **network},
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {
            "driver": "tb6612",
            "pins": {
                "pwmA": 1,
                "ain1": 2,
                "ain2": 3,
                "pwmB": 4,
                "bin1": 5,
                "bin2": 6,
            },
        },
    }
    validate_robot_config(raw)
    return RobotConfig(raw=raw)


def test_is_auto_connect():
    assert is_auto_connect("auto")
    assert is_auto_connect("AUTO")
    assert is_auto_connect("scout")
    assert not is_auto_connect(None)
    assert not is_auto_connect(DEFAULT_CONNECT)
    assert not is_auto_connect(SOFTAP_CONNECT)


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


def test_softap_default_unchanged():
    cfg = _mcu()
    assert requested_connect(cfg) == SOFTAP_CONNECT
    hdr = generate_robot_config_h(cfg)
    assert 'ROSIE_ZENOH_CONNECT = "tcp/192.168.4.2:7447"' in hdr
    assert "softap default" in hdr


def test_station_auto_bakes_lan_ip():
    cfg = _mcu(mode="station", connect="auto")
    assert requested_connect(cfg) == AUTO_CONNECT
    resolved = resolve_robot_connect(cfg, lan_ips=["192.168.8.2", "10.0.0.5"])
    assert resolved.locator == "tcp/192.168.8.2:7447"
    assert resolved.provenance.startswith("auto →")
    assert "tcp/10.0.0.5:7447" in resolved.candidates
    hdr = generate_robot_config_h(cfg, lan_ips=["192.168.8.2", "10.0.0.5"])
    assert 'ROSIE_ZENOH_CONNECT = "tcp/192.168.8.2:7447"' in hdr
    assert "auto → 192.168.8.2" in hdr
    assert "tcp/10.0.0.5:7447" in hdr


def test_station_omitted_connect_is_auto():
    cfg = _mcu(mode="station")
    assert requested_connect(cfg) == AUTO_CONNECT


def test_linux_omitted_connect_is_auto():
    raw = {
        "robot": "pi1",
        "fleet": "lab",
        "platform": "linux",
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {
            "driver": "tb6612",
            "pins": {
                "pwmA": 12,
                "ain1": 5,
                "ain2": 6,
                "pwmB": 13,
                "bin1": 20,
                "bin2": 21,
            },
        },
    }
    validate_robot_config(raw)
    cfg = RobotConfig(raw=raw)
    assert cfg.connect == AUTO_CONNECT


def test_explicit_connect_wins():
    cfg = _mcu(mode="station", connect="tcp/10.1.2.3:7447")
    resolved = resolve_robot_connect(cfg, lan_ips=["192.168.8.2"])
    assert resolved.locator == "tcp/10.1.2.3:7447"
    assert resolved.provenance == "robot.yaml"
    overridden = resolve_robot_connect(
        cfg, override="tcp/9.9.9.9:7447", lan_ips=["192.168.8.2"]
    )
    assert overridden.locator == "tcp/9.9.9.9:7447"
    assert overridden.provenance == "cli --connect"


def test_auto_unresolvable_raises():
    cfg = _mcu(mode="station", connect="auto")
    with pytest.raises(ValueError, match="no LAN IPv4"):
        resolve_robot_connect(cfg, lan_ips=[])


def test_invalid_connect_rejected():
    with pytest.raises(ValueError, match="network.connect"):
        _mcu(connect="not-a-locator")


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


def test_agent_defaults_to_auto():
    from rosie.agent.config import load_agent_config

    cfg = load_agent_config(None, robot="r", fleet="lab")
    assert cfg.connect == "auto"


def test_agent_install_omits_rosie_connect(tmp_path, monkeypatch):
    from rosie.agent.config import AgentConfig, write_agent_config
    from rosie.agent.runner import install_agent

    path = tmp_path / "agent.yaml"
    write_agent_config(
        path, AgentConfig(robot="r", fleet="lab", connect="tcp/1.2.3.4:7447")
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    unit = install_agent(config_path=path)
    text = unit.read_text(encoding="utf-8")
    assert "ROSIE_CONNECT" not in text
    assert f"--config {path}" in text
