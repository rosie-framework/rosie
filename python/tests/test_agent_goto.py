"""Agent goto helpers and agent.yaml nav keys (no rclpy)."""

from __future__ import annotations

from rosie.agent.config import AgentConfig, load_agent_config
from rosie.agent.goto import (
    ACCEPT,
    IGNORE_DUPLICATE,
    IGNORE_STALE,
    STATUS_ABORTED,
    STATUS_CANCELED,
    STATUS_SUCCEEDED,
    arbitrate_goto,
    rosie_nav_status,
)


def test_arbitrate_accept_when_idle():
    assert arbitrate_goto(False, None, 1) == ACCEPT
    assert arbitrate_goto(False, 5, 1) == ACCEPT
    assert arbitrate_goto(False, 5, None) == ACCEPT


def test_arbitrate_ignore_duplicate():
    assert arbitrate_goto(True, 5, 5) == IGNORE_DUPLICATE


def test_arbitrate_ignore_stale():
    assert arbitrate_goto(True, 5, 3) == IGNORE_STALE


def test_arbitrate_preempt_higher_id():
    assert arbitrate_goto(True, 5, 6) == ACCEPT


def test_arbitrate_accept_missing_id_while_navigating():
    assert arbitrate_goto(True, 5, None) == ACCEPT


def test_rosie_nav_status_succeeded():
    assert rosie_nav_status(STATUS_SUCCEEDED) == "succeeded"
    assert rosie_nav_status("STATUS_SUCCEEDED") == "succeeded"
    assert rosie_nav_status("succeeded") == "succeeded"


def test_rosie_nav_status_canceled():
    assert rosie_nav_status(STATUS_CANCELED) == "canceled"
    assert rosie_nav_status("canceled") == "canceled"


def test_rosie_nav_status_aborted():
    assert rosie_nav_status(STATUS_ABORTED) == "aborted"
    assert rosie_nav_status(0) == "aborted"
    assert rosie_nav_status("unknown") == "aborted"


def test_rosie_nav_status_host_cancel_wins():
    assert rosie_nav_status(STATUS_SUCCEEDED, canceled_by_host=True) == "canceled"
    assert rosie_nav_status(STATUS_ABORTED, canceled_by_host=True) == "canceled"


def test_profile_nav_defaults():
    cfg = load_agent_config(None, robot="r", fleet="lab", profile="turtlebot4")
    assert cfg.cmd_vel == "/cmd_vel"
    assert cfg.odom == "/odom"
    assert cfg.pose is None
    assert cfg.navigate_to_pose == "/navigate_to_pose"
    assert cfg.frame_id == "map"
    assert cfg.profile == "turtlebot4"


def test_yahboom_profiles():
    for name in ("rosmaster_x3", "rosmaster_m3_pro"):
        cfg = load_agent_config(None, robot="r", fleet="lab", profile=name)
        assert cfg.cmd_vel == "/cmd_vel"
        assert cfg.odom == "/odom"
        assert cfg.pose is None
        assert cfg.navigate_to_pose == "/navigate_to_pose"
        assert cfg.frame_id == "map"
        assert cfg.profile == name


def test_optional_pose_from_yaml(tmp_path):
    path = tmp_path / "agent.yaml"
    path.write_text(
        "robot: turtle1\n"
        "fleet: lab\n"
        "ros2:\n"
        "  pose: /amcl_pose\n"
        "  frame_id: map\n"
        "  navigate_to_pose: /navigate_to_pose\n",
        encoding="utf-8",
    )
    cfg = load_agent_config(path)
    assert cfg.pose == "/amcl_pose"
    assert cfg.frame_id == "map"
    assert cfg.navigate_to_pose == "/navigate_to_pose"


def test_to_dict_omits_empty_pose():
    cfg = AgentConfig(robot="r", fleet="lab")
    ros2 = cfg.to_dict()["ros2"]
    assert "pose" not in ros2
    assert ros2["navigate_to_pose"] == "/navigate_to_pose"
    assert ros2["frame_id"] == "map"


def test_to_dict_includes_pose_when_set():
    cfg = AgentConfig(robot="r", fleet="lab", pose="/amcl_pose")
    assert cfg.to_dict()["ros2"]["pose"] == "/amcl_pose"
