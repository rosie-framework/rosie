"""Tests for Linux camera support and jpeg_quality scale."""

from __future__ import annotations

import time

import pytest

from rosie import topics
from rosie.robot_config import (
    DEFAULT_JPEG_QUALITY,
    RobotConfig,
    generate_robot_config_h,
    jpeg_quality_to_esp,
    validate_robot_config,
    warn_jpeg_quality_scale,
)
from rosie.run.drivers import NullMotorDriver, build_camera
from rosie.run.runtime import MobileBaseRuntime
from rosie.session import Qos


def _base_mcu(**overrides):
    raw = {
        "robot": "testbot",
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


class _FakeCamera:
    def __init__(self, jpeg: bytes = b"\xff\xd8fakejpeg\xff\xd9") -> None:
        self.jpeg = jpeg
        self.closed = False
        self.reads = 0

    @classmethod
    def from_config(cls, cam: dict) -> _FakeCamera:
        return cls()

    def read_jpeg(self) -> bytes | None:
        self.reads += 1
        return self.jpeg

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self) -> None:
        self.pubs: list[tuple[str, bytes, Qos]] = []

    def publish(self, key: str, payload: bytes | dict, *, qos: Qos = Qos.STREAM) -> None:
        if isinstance(payload, dict):
            raise AssertionError("camera must publish raw bytes")
        self.pubs.append((key, payload, qos))

    def close(self) -> None:
        pass


def test_jpeg_quality_to_esp_default_and_clamps():
    assert jpeg_quality_to_esp(70) == 19
    assert jpeg_quality_to_esp(DEFAULT_JPEG_QUALITY) == 19
    assert jpeg_quality_to_esp(100) == 10
    assert jpeg_quality_to_esp(0) == 63
    assert jpeg_quality_to_esp(50) == 32


def test_codegen_translates_jpeg_quality():
    raw = _base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 70})
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "ROSIE_CAMERA_JPEG_QUALITY = 19" in hdr

    raw100 = _base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 100})
    hdr100 = generate_robot_config_h(RobotConfig(raw=raw100))
    assert "ROSIE_CAMERA_JPEG_QUALITY = 10" in hdr100

    raw0 = _base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 0})
    hdr0 = generate_robot_config_h(RobotConfig(raw=raw0))
    assert "ROSIE_CAMERA_JPEG_QUALITY = 63" in hdr0


def test_codegen_default_jpeg_quality():
    raw = _base_mcu(camera={"board": "esp32s3_eye"})
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert (
        f"ROSIE_CAMERA_JPEG_QUALITY = {jpeg_quality_to_esp(DEFAULT_JPEG_QUALITY)}"
        in hdr
    )


def test_jpeg_quality_out_of_range():
    raw = _base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 101})
    with pytest.raises(ValueError, match="0..100"):
        validate_robot_config(raw)
    raw_neg = _base_linux(camera={"driver": "picamera2", "jpeg_quality": -1})
    with pytest.raises(ValueError, match="0..100"):
        validate_robot_config(raw_neg)


def test_warn_jpeg_quality_old_scale():
    cfg = RobotConfig(
        raw=_base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 18})
    )
    warn = warn_jpeg_quality_scale(cfg)
    assert warn is not None
    assert "higher=better" in warn

    cfg_ok = RobotConfig(
        raw=_base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 70})
    )
    assert warn_jpeg_quality_scale(cfg_ok) is None


def test_linux_camera_drivers_validate():
    for drv in ("picamera2", "v4l2"):
        raw = _base_linux(camera={"driver": drv, "jpeg_quality": 70, "pub_hz": 2})
        validate_robot_config(raw)

    raw_byo = _base_linux(
        camera={"driver": "python", "class": "rosie.run.drivers:NullMotorDriver"}
    )
    validate_robot_config(raw_byo)


def test_linux_camera_python_requires_class():
    raw = _base_linux(camera={"driver": "python"})
    with pytest.raises(ValueError, match="camera.class"):
        validate_robot_config(raw)


def test_linux_camera_unknown_driver():
    raw = _base_linux(camera={"driver": "nope"})
    with pytest.raises(ValueError):
        validate_robot_config(raw)


def test_linux_camera_rejects_mcu_board_only():
    raw = _base_linux(camera={"driver": "esp32s3_eye"})
    with pytest.raises(ValueError, match="platform"):
        validate_robot_config(raw)


def test_mcu_camera_board_path_unchanged():
    raw = _base_mcu(camera={"board": "esp32s3_eye", "jpeg_quality": 70})
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_HAS_CAMERA 1" in hdr
    assert "#define ROSIE_CAMERA_ESP32S3_EYE 1" in hdr


def test_build_camera_none_without_section():
    cfg = RobotConfig(raw=_base_linux())
    assert build_camera(cfg) is None


def test_build_camera_byo(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("fake_cam_mod")
    mod.FakeCam = _FakeCamera  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_cam_mod", mod)

    raw = _base_linux(
        camera={"driver": "python", "class": "fake_cam_mod:FakeCam", "pub_hz": 5}
    )
    validate_robot_config(raw)
    cam = build_camera(RobotConfig(raw=raw))
    assert isinstance(cam, _FakeCamera)
    assert cam.read_jpeg().startswith(b"\xff\xd8")
    cam.close()


def test_camera_enable_toggle():
    raw = _base_linux(
        camera={
            "driver": "python",
            "class": "fake",
            "enable_default": True,
            "pub_hz": 2,
        }
    )
    rt = MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        camera=_FakeCamera(),
        open_session=False,
    )
    assert rt._camera_enabled is True
    rt._on_cmd({"op": "camera_enable", "value": False})
    assert rt._camera_enabled is False
    rt._on_cmd({"op": "camera_enable", "value": True})
    assert rt._camera_enabled is True
    rt._on_cmd({"op": "camera_enable", "value": None})
    assert rt._camera_enabled is False


def test_camera_thread_publishes_bulk():
    raw = _base_linux(
        camera={
            "driver": "python",
            "class": "fake",
            "enable_default": True,
            "pub_hz": 50,
        }
    )
    cam = _FakeCamera(jpeg=b"\xff\xd8hello\xff\xd9")
    rt = MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        camera=cam,
        open_session=False,
    )
    fake_sess = _FakeSession()
    rt.session = fake_sess  # type: ignore[assignment]
    rt._start_camera_thread()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not fake_sess.pubs:
        time.sleep(0.02)
    rt._stop_camera_thread()
    assert fake_sess.pubs, "expected at least one camera publish"
    key, payload, qos = fake_sess.pubs[0]
    assert key == topics.CAMERA_COMPRESSED
    assert payload == b"\xff\xd8hello\xff\xd9"
    assert qos == Qos.BULK


def test_camera_disabled_skips_publish():
    raw = _base_linux(
        camera={
            "driver": "python",
            "class": "fake",
            "enable_default": False,
            "pub_hz": 50,
        }
    )
    cam = _FakeCamera()
    rt = MobileBaseRuntime(
        RobotConfig(raw=raw),
        motors=NullMotorDriver(),
        camera=cam,
        open_session=False,
    )
    fake_sess = _FakeSession()
    rt.session = fake_sess  # type: ignore[assignment]
    rt._start_camera_thread()
    time.sleep(0.15)
    rt._stop_camera_thread()
    assert fake_sess.pubs == []
    assert cam.reads == 0
