"""Tests for host delivery classes."""

from __future__ import annotations

import zenoh

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


