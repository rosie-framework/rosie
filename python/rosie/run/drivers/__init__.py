"""Linux hardware drivers for ``rosie run``."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rosie.robot_config import RobotConfig


_LINUX_HINT = (
    'This driver needs the linux extra:\n'
    '  pip install "rosie[linux]"'
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


@runtime_checkable
class ImuReader(Protocol):
    def read_yaw_rate(self) -> float | None: ...

    def close(self) -> None: ...


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
        from rosie.run.drivers.tb6612 import Tb6612MotorDriver

        return Tb6612MotorDriver.from_config(motors)
    if driver == "pca9685":
        from rosie.run.drivers.pca9685 import Pca9685MotorDriver

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
        from rosie.run.drivers.gpio_encoder import GpioQuadratureEncoder

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
        from rosie.run.drivers.mpu6050 import Mpu6050Imu

        return Mpu6050Imu.from_config(imu)
    raise ValueError(f"unsupported linux imu.chip {chip!r}")


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
