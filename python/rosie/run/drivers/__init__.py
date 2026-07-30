"""Linux hardware drivers for ``rosie run``.

Layout mirrors MCU ``firmware/.../drivers/<category>/``:

``motors/``, ``encoders/``, ``imu/``, ``camera/``, ``range/``.

Factory helpers, protocols, and ``require_*`` stay in this package root;
``byo.py`` remains top-level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from rosie.robot_config import (
    DEFAULT_JPEG_QUALITY,
    RobotConfig,
    VL53_RANGE_CHIPS,
    default_range_limits,
    normalize_range_sensors,
)


_LINUX_HINT = (
    'This driver needs the linux extra:\n'
    '  pip install "rosie-framework[linux]"'
)

_CAMERA_OPENCV_HINT = (
    'v4l2 camera needs the camera extra:\n'
    '  pip install "rosie-framework[camera]"'
)

_PICAMERA2_HINT = (
    "picamera2 is not pip-installable. On Raspberry Pi OS:\n"
    "  sudo apt install -y python3-picamera2\n"
    "If you use a venv, create it with --system-site-packages so apt packages are visible."
)


@runtime_checkable
class MotorDriver(Protocol):
    def set_channels(self, channels: list[float]) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class EncoderReader(Protocol):
    def read_ticks(self) -> tuple[int, int]: ...

    def close(self) -> None: ...

    # Optional: ``zero()`` — clear cumulative ticks on pose zero (BYO may omit).


@runtime_checkable
class ImuReader(Protocol):
    def read_yaw_rate(self) -> float | None: ...

    def close(self) -> None: ...

    # Optional: ``recalibrate()`` — refresh gyro bias on pose zero (BYO may omit).


@runtime_checkable
class CameraSource(Protocol):
    def read_jpeg(self) -> bytes | None: ...

    def close(self) -> None: ...


@runtime_checkable
class RangeReader(Protocol):
    def read_range(self) -> float | None: ...

    def close(self) -> None: ...


@dataclass
class RangeMeta:
    sensor_id: str
    pub_hz: float = 10.0
    min_range: float = 0.04
    max_range: float = 4.0


class NullMotorDriver:
    """No-op motors (tests / dry-run descriptions)."""

    def __init__(self) -> None:
        self.last: list[float] = [0.0, 0.0]

    def set_channels(self, channels: list[float]) -> None:
        self.last = list(channels[:2]) if channels else [0.0, 0.0]

    def stop(self) -> None:
        self.last = [0.0, 0.0]

    def close(self) -> None:
        pass


def build_motors(cfg: RobotConfig) -> MotorDriver:
    motors = cfg.raw.get("motors") or {}
    if not motors:
        raise ValueError("robot.yaml: motors section required for platform: linux")
    driver = str(motors.get("driver", "tb6612"))
    if driver == "python":
        from rosie.run.drivers.byo import load_byo

        cls_path = motors.get("class")
        if not cls_path:
            raise ValueError("motors.driver=python requires motors.class")
        return load_byo(str(cls_path), motors)
    if driver == "tb6612":
        from rosie.run.drivers.motors.tb6612 import Tb6612MotorDriver

        return Tb6612MotorDriver.from_config(motors)
    if driver == "pca9685":
        from rosie.run.drivers.motors.pca9685 import Pca9685MotorDriver

        return Pca9685MotorDriver.from_config(motors)
    raise ValueError(f"unsupported linux motors.driver {driver!r}")


def build_encoders(cfg: RobotConfig) -> EncoderReader | None:
    enc = cfg.raw.get("encoders")
    if not enc:
        return None
    driver = str(enc.get("driver", "gpio_quadrature"))
    if driver == "python":
        from rosie.run.drivers.byo import load_byo

        cls_path = enc.get("class")
        if not cls_path:
            raise ValueError("encoders.driver=python requires encoders.class")
        return load_byo(str(cls_path), enc)
    if driver == "gpio_quadrature":
        from rosie.run.drivers.encoders.gpio_encoder import GpioQuadratureEncoder

        return GpioQuadratureEncoder.from_config(enc)
    raise ValueError(f"unsupported linux encoders.driver {driver!r}")


def build_imu(cfg: RobotConfig) -> ImuReader | None:
    imu = cfg.raw.get("imu")
    if not imu:
        return None
    chip = str(imu.get("chip", imu.get("driver", "mpu6050")))
    if chip == "python":
        from rosie.run.drivers.byo import load_byo

        cls_path = imu.get("class")
        if not cls_path:
            raise ValueError("imu.chip=python requires imu.class")
        return load_byo(str(cls_path), imu)
    if chip == "mpu6050":
        from rosie.run.drivers.imu.mpu6050 import Mpu6050Imu

        return Mpu6050Imu.from_config(imu)
    raise ValueError(f"unsupported linux imu.chip {chip!r}")


def build_camera(cfg: RobotConfig) -> CameraSource | None:
    cam = cfg.raw.get("camera")
    if not cam:
        return None
    driver = str(cam.get("driver", "picamera2"))
    if driver == "python":
        from rosie.run.drivers.byo import load_byo

        cls_path = cam.get("class")
        if not cls_path:
            raise ValueError("camera.driver=python requires camera.class")
        return load_byo(str(cls_path), cam)
    if driver == "picamera2":
        from rosie.run.drivers.camera.picamera2_cam import Picamera2Source

        return Picamera2Source.from_config(cam)
    if driver == "v4l2":
        from rosie.run.drivers.camera.v4l2_camera import V4l2CameraSource

        return V4l2CameraSource.from_config(cam)
    raise ValueError(f"unsupported linux camera.driver {driver!r}")


def build_range_sensors(
    cfg: RobotConfig,
) -> list[tuple[str, RangeReader, RangeMeta]]:
    """Open configured range sensors (YAML order). Soft-fail is caller's job."""
    if not cfg.raw.get("range"):
        return []
    out: list[tuple[str, RangeReader, RangeMeta]] = []
    sensors = normalize_range_sensors(cfg.raw)

    # Multi VL53: claim all XSHUT lines low, then raise each as we init.
    lgpio = None
    gpio = None
    xshut_pins = [
        int(s["xshut"])
        for s in sensors
        if s.get("xshut") is not None
        and str(s.get("chip", "vl53l1x")) in VL53_RANGE_CHIPS
    ]
    if xshut_pins:
        lgpio = require_lgpio()
        gpio = lgpio.gpiochip_open(0)
        for pin in xshut_pins:
            lgpio.gpio_claim_output(gpio, pin, 0)
        import time

        time.sleep(0.01)

    try:
        for sens in sensors:
            sid = str(sens["id"])
            chip = str(sens.get("chip", "vl53l1x"))
            dmin, dmax = default_range_limits(chip)
            meta = RangeMeta(
                sensor_id=sid,
                pub_hz=float(sens.get("pub_hz", 10) or 0),
                min_range=float(sens.get("min_range", dmin)),
                max_range=float(sens.get("max_range", dmax)),
            )
            if chip == "python":
                from rosie.run.drivers.byo import load_byo

                cls_path = sens.get("class")
                if not cls_path:
                    raise ValueError(
                        f"range.sensors.{sid}: chip=python requires class"
                    )
                reader = load_byo(str(cls_path), sens)
            elif chip in VL53_RANGE_CHIPS:
                if chip == "vl53l0x":
                    from rosie.run.drivers.range.vl53l0x import Vl53l0xRange as _RangeCls
                else:
                    from rosie.run.drivers.range.vl53l1x import Vl53l1xRange as _RangeCls

                xshut = sens.get("xshut")
                if xshut is not None and gpio is not None and lgpio is not None:
                    lgpio.gpio_write(gpio, int(xshut), 1)
                    import time

                    time.sleep(0.01)
                    # Driver must not reclaim the same GPIO line.
                    sens_noshut = {k: v for k, v in sens.items() if k != "xshut"}
                    reader = _RangeCls.from_config(sens_noshut)
                else:
                    reader = _RangeCls.from_config(sens)
            else:
                raise ValueError(f"unsupported linux range chip {chip!r}")
            out.append((sid, reader, meta))
    except Exception:
        for _sid, reader, _meta in out:
            try:
                reader.close()
            except Exception:
                pass
        if gpio is not None and lgpio is not None:
            try:
                lgpio.gpiochip_close(gpio)
            except Exception:
                pass
        raise

    # Keep chip handle open so XSHUT lines stay driven high for the session.
    # Attach to the first reader for cleanup if possible; otherwise close now
    # only when no xshut was used.
    if gpio is not None and out:
        setattr(out[0][1], "_rosie_xshut_gpio", gpio)
    elif gpio is not None and lgpio is not None:
        lgpio.gpiochip_close(gpio)
    return out


def describe_hardware(cfg: RobotConfig) -> list[str]:
    """Human-readable driver summary (no hardware open)."""
    lines: list[str] = []
    motors = cfg.raw.get("motors") or {}
    if motors:
        drv = motors.get("driver", "?")
        extra = f" class={motors.get('class')}" if drv == "python" else ""
        lines.append(f"motors:   {drv}{extra}")
    else:
        lines.append("motors:   (missing)")
    enc = cfg.raw.get("encoders")
    if enc:
        lines.append(f"encoders: {enc.get('driver', 'gpio_quadrature')}")
    else:
        lines.append("encoders: (none — dead-reckoning odometry)")
    imu = cfg.raw.get("imu")
    if imu:
        lines.append(f"imu:      {imu.get('chip', imu.get('driver', '?'))}")
    else:
        lines.append("imu:      (none)")
    cam = cfg.raw.get("camera")
    if cam:
        drv = cam.get("driver", "picamera2")
        extra = f" class={cam.get('class')}" if drv == "python" else ""
        lines.append(f"camera:   {drv}{extra}")
    else:
        lines.append("camera:   (none)")
    if cfg.raw.get("range"):
        try:
            sensors = normalize_range_sensors(cfg.raw)
            ids = ",".join(str(s["id"]) for s in sensors)
            lines.append(f"range:    {ids} ({len(sensors)})")
        except Exception as e:
            lines.append(f"range:    (invalid: {e})")
    else:
        lines.append("range:    (none)")
    return lines


def probe_drivers(cfg: RobotConfig) -> list[str]:
    """Validate drivers are importable / BYO classes resolve; do not open hardware."""
    notes: list[str] = []
    motors = cfg.raw.get("motors") or {}
    if motors:
        drv = str(motors.get("driver", "tb6612"))
        if drv == "python":
            from rosie.run.drivers.byo import resolve_byo_class

            cls = resolve_byo_class(str(motors.get("class")))
            notes.append(f"motors:   python → {cls.__module__}.{cls.__name__}")
        elif drv == "tb6612":
            require_lgpio()
            notes.append("motors:   tb6612 (lgpio ok)")
        elif drv == "pca9685":
            require_smbus2()
            notes.append("motors:   pca9685 (smbus2 ok)")
        else:
            notes.append(f"motors:   {drv}")

    enc = cfg.raw.get("encoders")
    if enc:
        drv = str(enc.get("driver", "gpio_quadrature"))
        if drv == "python":
            from rosie.run.drivers.byo import resolve_byo_class

            cls = resolve_byo_class(str(enc.get("class")))
            notes.append(f"encoders: python → {cls.__module__}.{cls.__name__}")
        elif drv == "gpio_quadrature":
            require_lgpio()
            notes.append("encoders: gpio_quadrature (lgpio ok)")
        else:
            notes.append(f"encoders: {drv}")
    else:
        notes.append("encoders: (none — dead-reckoning)")

    imu = cfg.raw.get("imu")
    if imu:
        chip = str(imu.get("chip", imu.get("driver", "mpu6050")))
        if chip == "python":
            from rosie.run.drivers.byo import resolve_byo_class

            cls = resolve_byo_class(str(imu.get("class")))
            notes.append(f"imu:      python → {cls.__module__}.{cls.__name__}")
        elif chip == "mpu6050":
            require_smbus2()
            notes.append("imu:      mpu6050 (smbus2 ok)")
        else:
            notes.append(f"imu:      {chip}")
    else:
        notes.append("imu:      (none)")

    cam = cfg.raw.get("camera")
    if cam:
        drv = str(cam.get("driver", "picamera2"))
        if drv == "python":
            from rosie.run.drivers.byo import resolve_byo_class

            cls = resolve_byo_class(str(cam.get("class")))
            notes.append(f"camera:   python → {cls.__module__}.{cls.__name__}")
        elif drv == "picamera2":
            require_picamera2()
            notes.append("camera:   picamera2 (import ok)")
        elif drv == "v4l2":
            require_cv2()
            notes.append("camera:   v4l2 (opencv ok)")
        else:
            notes.append(f"camera:   {drv}")
    else:
        notes.append("camera:   (none)")

    if cfg.raw.get("range"):
        sensors = normalize_range_sensors(cfg.raw)
        for sens in sensors:
            sid = sens["id"]
            chip = str(sens.get("chip", "vl53l1x"))
            if chip == "python":
                from rosie.run.drivers.byo import resolve_byo_class

                cls = resolve_byo_class(str(sens.get("class")))
                notes.append(
                    f"range/{sid}: python → {cls.__module__}.{cls.__name__}"
                )
            elif chip in ("vl53l1x", "vl53l0x"):
                require_smbus2()
                if sens.get("xshut") is not None:
                    require_lgpio()
                    notes.append(f"range/{sid}: {chip} (smbus2+lgpio ok)")
                else:
                    notes.append(f"range/{sid}: {chip} (smbus2 ok)")
            else:
                notes.append(f"range/{sid}: {chip}")
    else:
        notes.append("range:    (none)")
    return notes


def require_lgpio() -> Any:
    try:
        import lgpio
    except ImportError as e:
        raise ImportError(_LINUX_HINT) from e
    return lgpio


def require_smbus2() -> Any:
    try:
        import smbus2
    except ImportError as e:
        raise ImportError(_LINUX_HINT) from e
    return smbus2


def require_cv2() -> Any:
    try:
        import cv2
    except ImportError as e:
        raise ImportError(_CAMERA_OPENCV_HINT) from e
    return cv2


def require_picamera2() -> Any:
    try:
        from picamera2 import Picamera2
    except ImportError as e:
        raise ImportError(_PICAMERA2_HINT) from e
    return Picamera2


def camera_jpeg_quality(cam: dict[str, Any]) -> int:
    """Canonical 0–100 JPEG quality from a camera YAML section."""
    try:
        q = int(round(float(cam.get("jpeg_quality", DEFAULT_JPEG_QUALITY))))
    except (TypeError, ValueError):
        q = DEFAULT_JPEG_QUALITY
    return max(0, min(100, q))
