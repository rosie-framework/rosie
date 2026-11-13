"""Wire layout, CDR fixtures, and a laptop-side NavigateToPose query."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rosie.profiles import bridge_config, load_profile
from rosie.ros.action import nav_status_name, request_attachment
from rosie.ros.codec import decode, encode
from rosie.ros.envelope import command_envelope, envelope_expired, parse_envelope
from rosie.ros.keys import action_key, bridge_key, rmw_key, topic_key
from rosie.ros.schemas import schema_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_bridge_namespace_is_two_segments():
    assert bridge_key("/lab/bot1", "/cmd_vel") == "lab/bot1/cmd_vel"
    assert bridge_key("/lab/bot1", "/odom") == "lab/bot1/odom"
    goal = action_key("/lab/bot1", "/navigate_to_pose", "send_goal")
    assert goal == "lab/bot1/navigate_to_pose/_action/send_goal"


def test_rmw_humble_hash_and_jazzy_prefix():
    humble = rmw_key("/cmd_vel", "geometry_msgs/msg/Twist", distro="humble")
    assert humble.endswith("/TypeHashNotSupported")
    assert humble.startswith("0/cmd_vel/")
    jazzy = rmw_key(
        "/lab/bot1/cmd_vel",
        "geometry_msgs/msg/Twist",
        distro="jazzy",
        type_hash="abc",
    )
    assert jazzy.endswith("/RIHS01_abc")


def test_profile_key_matches_bridge_namespace():
    profile = load_profile("rosmaster_x3")
    assert profile.key_for("lab", "bot1", profile.cmd_vel) == "lab/bot1/cmd_vel"
    cfg = bridge_config(profile, fleet="lab", robot="bot1", connect="tcp/10.0.0.2:7447")
    assert cfg["plugins"]["ros2dds"]["namespace"] == "/lab/bot1"
    assert cfg["mode"] == "client"


def test_contract_fields_present_on_every_profile():
    from rosie.profiles import PROFILES

    for name in PROFILES:
        profile = load_profile(name)
        assert profile.cmd_vel.topic.startswith("/")
        assert profile.cmd_vel.type.startswith("geometry_msgs/msg/Twist")
        assert profile.pose.type in {
            "nav_msgs/msg/Odometry",
            "geometry_msgs/msg/PoseWithCovarianceStamped",
        }
        assert profile.link_loss in {"continue", "stop", "stop_after"}


def test_twist_fixture_roundtrip_across_distros():
    raw = (FIXTURES / "twist.cdr").read_bytes()
    assert raw[:4] == b"\x00\x01\x00\x00"
    decoded = decode("geometry_msgs/msg/Twist", raw, distro="humble")
    assert decoded["linear"]["x"] == pytest.approx(0.25)
    again = encode("geometry_msgs/msg/Twist", decoded, distro="lyrical")
    assert again == raw


def test_odometry_and_image_fixtures():
    odom = decode(
        "nav_msgs/msg/Odometry",
        (FIXTURES / "odometry.cdr").read_bytes(),
        distro="jazzy",
    )
    assert odom["pose"]["pose"]["position"]["x"] == pytest.approx(1.0)
    image = decode(
        "sensor_msgs/msg/CompressedImage",
        (FIXTURES / "compressed_image.cdr").read_bytes(),
        distro="jazzy",
    )
    assert bytes(image["data"]).startswith(b"\xff\xd8")


def test_send_goal_fixture():
    raw = (FIXTURES / "navigate_to_pose_send_goal.cdr").read_bytes()
    msg = decode(
        "nav2_msgs/action/NavigateToPose_SendGoal_Request",
        raw,
        distro="humble",
    )
    assert msg["goal"]["pose"]["pose"]["position"]["y"] == pytest.approx(2.0)
    assert bytes(msg["goal_id"]["uuid"]) == bytes(range(16))


def test_attachment_and_envelope():
    att = request_attachment(b"\x01" * 8, 3)
    assert att.startswith(b"rqh")
    assert att[-1:] == b"\x01"
    raw = command_envelope(command_id="abc", priority="interactive", ttl_s=1.0, now=100.0)
    parsed = parse_envelope(raw)
    assert parsed["id"] == "abc"
    assert envelope_expired(raw, now=200.0)
    assert not envelope_expired(raw, now=100.5)


def test_schema_names_the_type():
    text = schema_text("geometry_msgs/msg/Twist")
    assert "float64 x" in text
    assert "MSG: geometry_msgs/Vector3" in text


def test_topic_key_rmw_puts_fleet_in_the_name():
    key = topic_key(
        transport="rmw_zenoh",
        fleet="lab",
        robot="bot1",
        topic="/cmd_vel",
        ros_type="geometry_msgs/msg/Twist",
        distro="humble",
    )
    assert key.startswith("0/lab/bot1/cmd_vel/")


def test_mcap_export_uses_ros2_schema(tmp_path):
    import base64

    from rosie.bag import export_mcap
    from rosie.ros.codec import encode

    raw = encode(
        "geometry_msgs/msg/Twist",
        {"linear": {"x": 0.25}},
        distro="jazzy",
    )
    bag = tmp_path / "lab.rosiebag"
    header = {
        "rosiebag": "rosiebag-v1",
        "fleet": "lab",
        "selector": "**",
        "types": {"lab/bot1/cmd_vel": "geometry_msgs/msg/Twist"},
    }
    line = {
        "t": 1.0,
        "key": "lab/bot1/cmd_vel",
        "encoding": "b64",
        "payload": base64.b64encode(raw).decode("ascii"),
    }
    bag.write_text(
        json.dumps(header) + "\n" + json.dumps(line) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "lab.mcap"
    export_mcap(bag, out, fleet="lab")
    blob = out.read_bytes()
    assert b"ros2msg" in blob
    assert b"geometry_msgs/msg/Twist" in blob


def test_nav_status_names():
    assert nav_status_name(4) == "succeeded"
    assert nav_status_name(5) == "canceled"
    assert nav_status_name(6) == "aborted"
    assert json.dumps({"ok": True})
