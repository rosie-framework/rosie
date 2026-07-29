"""Tests for delivery classes and MobileBaseRuntime command arbitration."""

from __future__ import annotations

import time

import zenoh

from rosie.robot_config import RobotConfig
from rosie.run.drivers import NullMotorDriver
from rosie.run.runtime import DriveMode, MobileBaseRuntime
from rosie.session import Qos, qos_put_kwargs


def test_qos_put_kwargs_stream():
    kw = qos_put_kwargs(Qos.STREAM)
    assert kw["congestion_control"] == zenoh.CongestionControl.DROP
    assert kw["priority"] == zenoh.Priority.DATA
    assert kw["express"] is False


def test_qos_put_kwargs_command():
    kw = qos_put_kwargs(Qos.COMMAND)
    assert kw["congestion_control"] == zenoh.CongestionControl.BLOCK
    assert kw["priority"] == zenoh.Priority.INTERACTIVE_HIGH
    assert kw["express"] is True


def test_qos_put_kwargs_critical():
    kw = qos_put_kwargs(Qos.CRITICAL)
    assert kw["congestion_control"] == zenoh.CongestionControl.BLOCK
    assert kw["priority"] == zenoh.Priority.REAL_TIME
    assert kw["express"] is True


def test_qos_put_kwargs_bulk():
    kw = qos_put_kwargs(Qos.BULK)
    assert kw["congestion_control"] == zenoh.CongestionControl.DROP
    assert kw["priority"] == zenoh.Priority.DATA_LOW
    assert kw["express"] is False


def _runtime() -> MobileBaseRuntime:
    raw = {
        "robot": "testbot",
        "platform": "linux",
        "network": {"connect": "tcp/127.0.0.1:7447"},
        "base": {
            "type": "diff_drive",
            "wheel_diameter": 0.068,
            "wheel_base": 0.13,
            "ticks_per_rev": 1440,
        },
        "motors": {"driver": "null"},
        "control": {"dt_ms": 20, "teleop": {"timeout_ms": 400}},
    }
    return MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        open_session=False,
    )


def test_stop_alone_goes_idle():
    rt = _runtime()
    rt._on_cmd_vel({"v": 0.2, "w": 0.0})
    rt.tick()
    assert rt._mode == DriveMode.MANUAL
    rt._on_cmd({"op": "stop"})
    rt.tick()
    assert rt._mode == DriveMode.IDLE


def test_stop_beats_older_cmd_vel_same_tick():
    rt = _runtime()
    t0 = time.monotonic()
    with rt._lock:
        rt._cmd_v = 0.2
        rt._cmd_w = 0.0
        rt._last_cmd_vel_t = t0
        rt._cmd_vel_seen = True
        rt._stop_req = True
        rt._stop_t = t0 + 0.001
    rt.tick()
    assert rt._mode == DriveMode.IDLE


def test_newer_cmd_vel_after_stop_enters_manual():
    rt = _runtime()
    t0 = time.monotonic()
    with rt._lock:
        rt._stop_req = True
        rt._stop_t = t0
        rt._cmd_v = 0.2
        rt._cmd_w = 0.0
        rt._last_cmd_vel_t = t0 + 0.001
        rt._cmd_vel_seen = True
    rt.tick()
    assert rt._mode == DriveMode.MANUAL


def test_sticky_stop_across_ticks():
    """Older latched cmd_vel must not resurrect Manual on the next tick."""
    rt = _runtime()
    t0 = time.monotonic()
    with rt._lock:
        rt._cmd_v = 0.2
        rt._cmd_w = 0.0
        rt._last_cmd_vel_t = t0
        rt._cmd_vel_seen = True
    rt.tick()
    assert rt._mode == DriveMode.MANUAL

    with rt._lock:
        rt._stop_req = True
        rt._stop_t = t0 + 0.01
        # Stale stream still present as last_cmd_vel_t; no new cmd_vel_seen.
        rt._cmd_vel_seen = False
    rt.tick()
    assert rt._mode == DriveMode.IDLE

    # Next tick: still no newer cmd_vel — stay Idle.
    rt.tick()
    assert rt._mode == DriveMode.IDLE


def test_goto_accept_when_idle():
    rt = _runtime()
    rt._on_goto({"x": 1.0, "y": 0.5, "goal_id": 1})
    rt.tick()
    assert rt._navigating is True
    assert rt._active_goal_id == 1
    assert rt._mode == DriveMode.AUTO


def test_goto_ignore_duplicate_goal_id():
    rt = _runtime()
    rt._on_goto({"x": 1.0, "y": 0.0, "goal_id": 5})
    rt.tick()
    assert rt._navigating is True
    assert rt._active_goal_id == 5

    rt._on_goto({"x": 2.0, "y": 0.0, "goal_id": 5})
    rt.tick()
    assert rt._navigating is True
    assert rt._active_goal_id == 5
    assert rt._target_x == 1.0  # not replaced


def test_goto_ignore_stale_goal_id():
    rt = _runtime()
    rt._on_goto({"x": 1.0, "y": 0.0, "goal_id": 5})
    rt.tick()
    rt._on_goto({"x": 0.0, "y": 0.0, "goal_id": 3})
    rt.tick()
    assert rt._navigating is True
    assert rt._active_goal_id == 5
    assert rt._target_x == 1.0


def test_goto_preempt_higher_goal_id():
    rt = _runtime()
    rt._on_goto({"x": 1.0, "y": 0.0, "goal_id": 5})
    rt.tick()
    rt._on_goto({"x": 2.0, "y": 0.0, "goal_id": 6})
    rt.tick()
    assert rt._navigating is True
    assert rt._active_goal_id == 6
    assert rt._target_x == 2.0
