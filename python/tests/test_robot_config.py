"""Tests for robot.yaml validation and MCU robot_config.h codegen."""

from __future__ import annotations

import pytest

from rosie.robot_config import RobotConfig, generate_robot_config_h, validate_robot_config


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


def test_gen_config_tb6612_macros():
    raw = _base_mcu()
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_MOTORS_TB6612 1" in hdr
    assert "ROSIE_MOTORS_L298N" not in hdr
    assert "ROSIE_PIN_PWMA" in hdr
    assert "#define ROSIE_HAS_ENCODERS 0" in hdr
    assert "#define ROSIE_HAS_IMU 0" in hdr
    assert "#define ROSIE_HAS_CAMERA 0" in hdr


def test_gen_config_l298n_macros():
    raw = _base_mcu(
        motors={
            "driver": "l298n",
            "pins": {
                "ena": 10,
                "in1": 11,
                "in2": 12,
                "enb": 13,
                "in3": 14,
                "in4": 15,
            },
        }
    )
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_MOTORS_L298N 1" in hdr
    assert "ROSIE_MOTORS_TB6612" not in hdr
    assert "ROSIE_PIN_ENA" in hdr
    assert 'ROSIE_MOTORS_DRIVER_ID "l298n"' in hdr


def test_drv8833_planned_rejected():
    raw = _base_mcu(motors={"driver": "drv8833", "pins": {}})
    with pytest.raises(ValueError, match="planned"):
        validate_robot_config(raw)


def test_encoders_omit_and_present():
    raw = _base_mcu()
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_HAS_ENCODERS 0" in hdr

    raw2 = _base_mcu(
        encoders={
            "driver": "quad_encoder",
            "pins": {"left": [1, 2], "right": [3, 4]},
        }
    )
    validate_robot_config(raw2)
    hdr2 = generate_robot_config_h(RobotConfig(raw=raw2))
    assert "#define ROSIE_HAS_ENCODERS 1" in hdr2
    assert "#define ROSIE_ENCODERS_QUAD_ENCODER 1" in hdr2


def test_camera_esp32s3_eye_vs_custom():
    raw = _base_mcu(camera={"board": "esp32s3_eye"})
    validate_robot_config(raw)
    hdr = generate_robot_config_h(RobotConfig(raw=raw))
    assert "#define ROSIE_HAS_CAMERA 1" in hdr
    assert "#define ROSIE_CAMERA_ESP32S3_EYE 1" in hdr
    assert "ROSIE_CAMERA_CUSTOM" not in hdr

    raw_custom = _base_mcu(
        camera={
            "board": "custom",
            "pins": {
                "xclk": 15,
                "siod": 4,
                "sioc": 5,
                "y9": 16,
                "y8": 17,
                "y7": 18,
                "y6": 12,
                "y5": 10,
                "y4": 8,
                "y3": 9,
                "y2": 11,
                "vsync": 6,
                "href": 7,
                "pclk": 13,
            },
        }
    )
    validate_robot_config(raw_custom)
    hdr_c = generate_robot_config_h(RobotConfig(raw=raw_custom))
    assert "#define ROSIE_CAMERA_CUSTOM 1" in hdr_c
    assert "ROSIE_CAM_XCLK" in hdr_c


def test_camera_custom_requires_pins():
    raw = _base_mcu(camera={"board": "custom"})
    with pytest.raises(ValueError, match="camera.pins"):
        validate_robot_config(raw)


def test_l298n_requires_pin_keys():
    raw = _base_mcu(motors={"driver": "l298n", "pins": {"ena": 1}})
    with pytest.raises(ValueError, match="motors.pins"):
        validate_robot_config(raw)
