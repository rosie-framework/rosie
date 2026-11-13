"""Watchdog decisions without ROS."""

from rosie.watchdog.policy import WatchdogPolicy


def test_estop_holds_zero():
    policy = WatchdogPolicy()
    policy.on_twist(0.4, 0.1, now=10.0)
    policy.on_estop()
    v, w, reason = policy.tick(11.0)
    assert (v, w, reason) == (0.0, 0.0, "estop")


def test_deadman_zeros_only_after_motion():
    policy = WatchdogPolicy(deadman_s=0.5, gate=False)
    policy.on_twist(0.2, 0.0, now=10.0)
    assert policy.tick(10.2)[2] == "ok"
    v, w, reason = policy.tick(11.0)
    assert (v, w, reason) == (0.0, 0.0, "deadman")
    assert policy.tick(12.0)[0] is None


def test_gate_forwards_while_fresh():
    policy = WatchdogPolicy(deadman_s=0.5, gate=True)
    policy.on_twist(0.3, 0.0, now=5.0)
    assert policy.tick(5.2) == (0.3, 0.0, "forward")
    assert policy.tick(6.0) == (0.0, 0.0, "idle")


def test_link_loss_stop_after():
    policy = WatchdogPolicy(link_loss="stop_after", link_loss_s=2.0)
    policy.on_router(0.0)
    assert policy.tick(1.0)[2] == "ok"
    assert policy.tick(3.0)[2] == "link_loss"


def test_link_loss_continue():
    policy = WatchdogPolicy(link_loss="continue", link_loss_s=0.1)
    policy.on_router(0.0)
    assert policy.tick(10.0)[2] == "ok"
