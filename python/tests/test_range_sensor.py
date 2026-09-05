"""Tests for multi-sensor range / VL53L1X config, median, and publish."""

from __future__ import annotations

import time

import pytest

from rosie import topics
from rosie.robot_config import (
    MAX_RANGE_SENSORS,
    RobotConfig,
    generate_robot_config_h,
    normalize_range_sensors,
    validate_robot_config,
)
from rosie.run.drivers import NullMotorDriver, RangeMeta
from rosie.run.range_filter import MedianWindow
from rosie.run.runtime import MobileBaseRuntime
from rosie.session import Qos


def _base_mcu(**overrides):
    raw = {
        "robot": "testbot",
        "fleet": "lab",
        "network": {"mode": "softap", "ssid": "x", "password": "y"},
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
    raw.update(overrides)
    return raw


def _base_linux(**overrides):
    raw = {
        "robot": "pibot",
        "fleet": "lab",
        "platform": "linux",
        "network": {"connect": "tcp/127.0.0.1:7447"},
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
    raw.update(overrides)
    return raw


class _FakeRange:
    def __init__(self, values: list[float | None] | None = None) -> None:
        self._values = list(values or [0.4])
        self._i = 0
        self.closed = False

    @classmethod
    def from_config(cls, sens: dict) -> _FakeRange:
        return cls()

    def read_range(self) -> float | None:
        if not self._values:
            return None
        v = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return v

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self) -> None:
        self.pubs: list[tuple[str, dict, Qos]] = []

    def publish(self, key: str, payload, *, qos: Qos = Qos.STREAM) -> None:
        import json

        if isinstance(payload, (bytes, bytearray)):
            doc = json.loads(payload.decode("utf-8"))
        else:
            doc = payload
        self.pubs.append((key, doc, qos))

    def close(self) -> None:
        pass


def test_range_id_validation():
    raw = _base_linux(
        range={
            "sensors": {
                "front/left": {"chip": "vl53l1x", "i2c": {"bus": 1, "addr": 0x29}}
            }
        }
    )
    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_-\]+"):
        validate_robot_config(raw)

    raw_ok = _base_linux(
        range={
            "sensors": {
                "front_left": {"chip": "vl53l1x", "i2c": {"bus": 1, "addr": 0x29}}
            }
        }
    )
    validate_robot_config(raw_ok)


def test_range_multi_requires_xshut():
    raw = _base_mcu(
        range={
            "i2c": {"sda": 1, "scl": 2},
            "sensors": {
                "front_left": {"chip": "vl53l1x", "i2c": {"addr": 0x29}},
                "front_right": {"chip": "vl53l1x", "i2c": {"addr": 0x30}},
            },
        }
    )
    with pytest.raises(ValueError, match="xshut"):
        validate_robot_config(raw)

    raw_ok = _base_mcu(
        range={
            "i2c": {"sda": 1, "scl": 2},
            "sensors": {
                "front_left": {
                    "chip": "vl53l1x",
                    "i2c": {"addr": 0x29},
                    "xshut": 7,
                },
                "front_right": {
                    "chip": "vl53l1x",
                    "i2c": {"addr": 0x30},
                    "xshut": 8,
                },
            },
        }
    )
    validate_robot_config(raw_ok)


def test_range_max_sensors():
    sensors = {
        f"s{i}": {"chip": "vl53l1x", "i2c": {"bus": 1, "addr": 0x29 + i}, "xshut": 10 + i}
        for i in range(MAX_RANGE_SENSORS + 1)
    }
    raw = _base_linux(range={"sensors": sensors})
    with pytest.raises(ValueError, match="at most"):
        validate_robot_config(raw)


def test_codegen_range_macros():
    raw = _base_mcu(
        range={
            "i2c": {"sda": 1, "scl": 2},
            "pub_hz": 10,
            "sensors": {
                "front": {"chip": "vl53l1x", "i2c": {"addr": 0x29}},
            },
        }
    )
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_HAS_RANGE 1" in hdr
    assert "ROSIE_RANGE_COUNT = 1" in hdr
    assert "ROSIE_RANGE_MEDIAN_WINDOW" in hdr
    assert '"front"' in hdr
    assert "ROSIE_RANGE_CHIPS" in hdr
    assert "ROSIE_RANGE_VL53L1X 1" in hdr


def test_vl53l0x_validates_and_codegens():
    raw = _base_mcu(
        range={
            "i2c": {"sda": 1, "scl": 2},
            "sensors": {
                "front": {"chip": "vl53l0x", "i2c": {"addr": 0x29}},
            },
        }
    )
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "ROSIE_RANGE_VL53L0X 1" in hdr
    assert "ROSIE_RANGE_CHIP_VL53L0X" in hdr


def test_mixed_vl53_requires_xshut():
    raw = _base_linux(
        range={
            "sensors": {
                "a": {"chip": "vl53l0x", "i2c": {"bus": 1, "addr": 0x29}},
                "b": {"chip": "vl53l1x", "i2c": {"bus": 1, "addr": 0x30}},
            }
        }
    )
    with pytest.raises(ValueError, match="xshut"):
        validate_robot_config(raw)

    raw_ok = _base_linux(
        range={
            "sensors": {
                "a": {
                    "chip": "vl53l0x",
                    "i2c": {"bus": 1, "addr": 0x29},
                    "xshut": 5,
                },
                "b": {
                    "chip": "vl53l1x",
                    "i2c": {"bus": 1, "addr": 0x30},
                    "xshut": 6,
                },
            }
        }
    )
    validate_robot_config(raw_ok)


def test_normalize_merges_defaults():
    raw = _base_linux(
        range={
            "pub_hz": 5,
            "min_range": 0.05,
            "sensors": {
                "a": {"chip": "vl53l1x", "i2c": {"bus": 1, "addr": 0x29}, "pub_hz": 20},
            },
        }
    )
    sensors = normalize_range_sensors(raw)
    assert sensors[0]["id"] == "a"
    assert sensors[0]["pub_hz"] == 20
    assert sensors[0]["min_range"] == 0.05


def test_median_window():
    w = MedianWindow(5)
    assert w.push(1.0) == 1.0
    assert w.push(5.0) == 5.0  # sorted [1,5] mid index 1 -> 5
    vals = [1.0, 2.0, 10.0, 3.0, 4.0]
    w.clear()
    med = 0.0
    for v in vals:
        med = w.push(v)
    assert med == 3.0


def test_runtime_publishes_range_topics(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("fake_range_mod")
    mod.FakeRange = _FakeRange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_range_mod", mod)

    raw = _base_linux(
        range={
            "sensors": {
                "front_left": {
                    "chip": "python",
                    "class": "fake_range_mod:FakeRange",
                    "pub_hz": 50,
                },
                "front_right": {
                    "chip": "python",
                    "class": "fake_range_mod:FakeRange",
                    "pub_hz": 50,
                },
            }
        }
    )
    validate_robot_config(raw)
    left = _FakeRange([0.5, 0.4, 0.6, 0.45, 0.55])
    right = _FakeRange([1.0, 1.1, 0.9, 1.0, 1.05])
    rt = MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        range_sensors=[
            ("front_left", left, RangeMeta("front_left", pub_hz=50)),
            ("front_right", right, RangeMeta("front_right", pub_hz=50)),
        ],
        open_session=False,
    )
    sess = _FakeSession()
    rt.session = sess  # type: ignore[assignment]
    for _ in range(5):
        rt._publish_range("front_left", left, RangeMeta("front_left", pub_hz=50))
        rt._publish_range("front_right", right, RangeMeta("front_right", pub_hz=50))
    keys = {k for k, _d, _q in sess.pubs}
    assert topics.range_topic("front_left") in keys
    assert topics.range_topic("front_right") in keys
    left_docs = [d for k, d, _q in sess.pubs if k.endswith("front_left")]
    assert left_docs[-1]["id"] == "front_left"
    assert "range_median" in left_docs[-1]
    assert left_docs[-1]["ok"] is True


def test_failed_read_skips_median():
    w = MedianWindow(5)
    w.push(1.0)
    w.push(2.0)
    before = w.median()
    # simulate failed read: do not push
    assert w.median() == before
