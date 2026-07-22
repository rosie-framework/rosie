"""Load / validate robot.yaml and generate firmware robot_config.h."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_BASE = frozenset({"diff_drive"})
PLANNED_BASE = frozenset({"mecanum", "ackermann"})
SUPPORTED_VELOCITY = frozenset({"pid"})


@dataclass
class DriverEntry:
    id: str
    category: str
    status: str
    description: str
    yaml_key: str = ""
    aliases: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["mcu"])


def registry_path() -> Path:
    from rosie.paths import firmware_dir

    return firmware_dir() / "drivers" / "registry.yaml"


def load_registry(path: Path | None = None) -> list[DriverEntry]:
    p = path or registry_path()
    data = _load_yaml_or_json(p)
    out: list[DriverEntry] = []
    for raw in data.get("drivers", []):
        platforms = raw.get("platforms")
        if platforms is None:
            platforms = ["mcu"]
        out.append(
            DriverEntry(
                id=str(raw["id"]),
                category=str(raw.get("category", "")),
                status=str(raw.get("status", "planned")),
                description=str(raw.get("description", "")),
                yaml_key=str(raw.get("yaml_key", "")),
                aliases=[str(a) for a in raw.get("aliases", [])],
                deps=[str(d) for d in raw.get("deps", [])],
                platforms=[str(x) for x in platforms],
            )
        )
    return out


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError(
                "PyYAML is required to load robot.yaml / registry.yaml. "
                "Install with: pip install pyyaml"
            ) from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping at top level")
    return data


def _resolve_id(raw: str, entries: list[DriverEntry], category: str | None = None) -> str:
    """Map alias → canonical id; raise if unknown."""
    for e in entries:
        if category and e.category != category:
            continue
        if e.id == raw or raw in e.aliases:
            return e.id
    raise ValueError(
        f"unknown id {raw!r}"
        + (f" for category {category}" if category else "")
        + f". See `rosie drivers list` or docs/drivers.md."
    )


def _require_supported(
    entries: list[DriverEntry],
    id_: str,
    category: str,
    *,
    platform: str = "mcu",
) -> DriverEntry:
    for e in entries:
        if e.id == id_ and e.category == category:
            if platform not in e.platforms:
                raise ValueError(
                    f"{category} id {id_!r} is not available on platform={platform!r} "
                    f"(platforms={e.platforms}). See `rosie drivers list --platform {platform}`."
                )
            if e.status != "supported":
                raise ValueError(
                    f"{category} id {id_!r} is status={e.status!r} (not implemented yet). "
                    "Use a supported id from `rosie drivers list`, or the BYO driver escape hatch."
                )
            return e
    raise ValueError(f"unknown {category} id {id_!r}")


@dataclass
class RobotConfig:
    raw: dict[str, Any]
    path: Path | None = None

    @property
    def robot(self) -> str:
        return str(self.raw["robot"])

    @property
    def fleet(self) -> str | None:
        f = self.raw.get("fleet")
        if f is None or f == "" or f is False:
            return None
        return str(f)

    @property
    def connect(self) -> str:
        return str(self.raw.get("network", {}).get("connect", "tcp/192.168.4.2:7447"))

    @property
    def network_mode(self) -> str:
        return str(self.raw.get("network", {}).get("mode", "softap"))

    @property
    def platform(self) -> str:
        p = self.raw.get("platform", "mcu")
        return str(p or "mcu").strip().lower()


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay onto a shallow copy of base (dicts only)."""
    out: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_robot_config(path: str | Path) -> RobotConfig:
    """Parse and validate a robot.yaml (or .yml / .json).

    If ``robot.local.yaml`` (or ``.yml`` / ``.json``) sits next to the primary
    file, it is deep-merged on top.
    """
    p = Path(path).expanduser().resolve()
    raw = _load_yaml_or_json(p)
    for name in ("robot.local.yaml", "robot.local.yml", "robot.local.json"):
        local = p.parent / name
        if local.is_file():
            overlay = _load_yaml_or_json(local)
            if not isinstance(overlay, dict):
                raise ValueError(f"{local}: expected mapping at top level")
            raw = _deep_merge(raw, overlay)
            break
    validate_robot_config(raw)
    return RobotConfig(raw=raw, path=p)


def validate_robot_config(raw: dict[str, Any], registry: list[DriverEntry] | None = None) -> None:
    if "robot" not in raw or not str(raw["robot"]).strip():
        raise ValueError("robot.yaml: missing required field 'robot'")
    entries = registry if registry is not None else load_registry()

    platform = str(raw.get("platform", "mcu") or "mcu").strip().lower()
    if platform not in ("mcu", "linux"):
        raise ValueError(
            f"robot.yaml: platform must be 'mcu' or 'linux' (got {platform!r})"
        )

    if platform == "mcu":
        net = raw.get("network") or {}
        mode = str(net.get("mode", "softap"))
        mode = _resolve_id(mode, entries, "network")
        _require_supported(entries, mode, "network", platform=platform)

    base = raw.get("base") or {}
    btype = str(base.get("type", "diff_drive"))
    btype = _resolve_id(btype, entries, "base")
    _require_supported(entries, btype, "base", platform=platform)

    motors = raw.get("motors") or {}
    if motors:
        drv = str(motors.get("driver", "tb6612"))
        drv = _resolve_id(drv, entries, "motors")
        _require_supported(entries, drv, "motors", platform=platform)
        if platform == "linux" and drv == "python" and not motors.get("class"):
            raise ValueError("motors.driver=python requires motors.class")
    elif platform == "linux":
        raise ValueError("robot.yaml: motors section required for platform: linux")

    enc = raw.get("encoders")
    if enc and platform == "linux":
        edrv = str(enc.get("driver", "gpio_quadrature"))
        edrv = _resolve_id(edrv, entries, "encoders")
        _require_supported(entries, edrv, "encoders", platform=platform)
        if edrv == "python" and not enc.get("class"):
            raise ValueError("encoders.driver=python requires encoders.class")

    imu = raw.get("imu")
    if imu:
        chip = str(imu.get("chip", "mpu6050"))
        chip = _resolve_id(chip, entries, "imu")
        _require_supported(entries, chip, "imu", platform=platform)
        if platform == "linux" and chip == "python" and not imu.get("class"):
            raise ValueError("imu.chip=python requires imu.class")

    cam = raw.get("camera")
    if cam:
        if platform == "linux":
            raise ValueError(
                "robot.yaml: camera is not supported on platform: linux yet"
            )
        board = str(cam.get("board", "esp32s3_eye"))
        board = _resolve_id(board, entries, "camera")
        _require_supported(entries, board, "camera", platform=platform)

    control = raw.get("control") or {}
    velocity = control.get("velocity")
    if velocity is not None:
        if not isinstance(velocity, dict):
            raise ValueError("robot.yaml: control.velocity must be a mapping")
        vtype = str(velocity.get("type", "pid"))
        if vtype not in SUPPORTED_VELOCITY:
            raise ValueError(
                f"robot.yaml: control.velocity.type {vtype!r} is unsupported "
                f"(v1 supports: {sorted(SUPPORTED_VELOCITY)})"
            )


def find_robot_yaml(project_dir: str | Path) -> Path | None:
    root = Path(project_dir).expanduser().resolve()
    for name in ("robot.yaml", "robot.yml", "robot.json"):
        p = root / name
        if p.is_file():
            return p
    return None


def _c_str(s: str | None) -> str:
    if s is None:
        return "nullptr"
    esc = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


def _c_float(v: Any, default: float = 0.0) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = float(default)
    # C++ requires a decimal point or exponent for the `f` suffix (else UDL parse error).
    body = f"{x:.9g}"
    if "e" not in body.lower() and "." not in body:
        body += ".0"
    return body + "f"


def _c_int(v: Any, default: int = 0) -> str:
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return str(default)


def generate_robot_config_h(cfg: RobotConfig) -> str:
    """Emit C++ header with constants for the robot firmware."""
    if cfg.platform == "linux":
        raise ValueError(
            "generate_robot_config_h is MCU-only; "
            "platform: linux uses `rosie run` (no codegen)."
        )
    r = cfg.raw
    net = r.get("network") or {}
    base = r.get("base") or {}
    motors = r.get("motors") or {}
    pins = motors.get("pins") or {}
    pwm = motors.get("pwm") or {}
    enc = (r.get("encoders") or {}).get("pins") or {}
    left = enc.get("left") or [0, 0]
    right = enc.get("right") or [0, 0]
    control = r.get("control") or {}
    teleop = control.get("teleop") or {}
    goto = control.get("goto") or {}
    velocity = control.get("velocity") or {}
    imu = r.get("imu") or {}
    i2c = imu.get("i2c") or {}
    cam = r.get("camera") or {}

    fleet = cfg.fleet
    fleet_line = (
        f"static const char* ROSIE_FLEET_ID = {_c_str(fleet)};"
        if fleet
        else "static const char* ROSIE_FLEET_ID = nullptr;"
    )

    lines = [
        "// AUTO-GENERATED by `rosie mcu gen-config` — do not edit by hand.",
        "// Source: robot.yaml",
        "//",
        "// Prefer <rosie/diff_drive_stack.h> (include this header after this one)",
        "// so you do not wire ROSIE_* values by hand. Typical main.cpp:",
        "//   #include \"generated/robot_config.h\"",
        "//   #include <rosie/diff_drive_stack.h>",
        "//   rosie::DiffDriveStack stack;",
        "//   void setup() { Serial.begin(115200); delay(300); stack.begin(); }",
        "//   void loop() { stack.loop(); }",
        "//",
        "#pragma once",
        "",
        "#define ROSIE_ROBOT_CONFIG_H 1",
        "",
        "#include <stdint.h>",
        "",
    ] + [
        f"static const char* ROSIE_ROBOT_ID = {_c_str(cfg.robot)};",
        fleet_line,
        f"static const char* ROSIE_NETWORK_MODE = {_c_str(str(net.get('mode', 'softap')))};",
        f"static const char* ROSIE_WIFI_SSID = {_c_str(str(net.get('ssid', '')))};",
        f"static const char* ROSIE_WIFI_PASSWORD = {_c_str(str(net.get('password', '')))};",
        f"static const char* ROSIE_ZENOH_CONNECT = {_c_str(str(net.get('connect', 'tcp/192.168.4.2:7447')))};",
        f"static const char* ROSIE_ZENOH_MODE = {_c_str(str(net.get('zenoh_mode', 'client')))};",
        "",
        f"static const float ROSIE_WHEEL_DIAMETER = {_c_float(base.get('wheel_diameter', 0.068))};",
        f"static const float ROSIE_WHEEL_BASE = {_c_float(base.get('wheel_base', 0.13))};",
        f"static const float ROSIE_TICKS_PER_REV = {_c_float(base.get('ticks_per_rev', 1440))};",
        "",
        f"static const int ROSIE_PIN_PWMA = {_c_int(pins.get('pwmA'))};",
        f"static const int ROSIE_PIN_AIN1 = {_c_int(pins.get('ain1'))};",
        f"static const int ROSIE_PIN_AIN2 = {_c_int(pins.get('ain2'))};",
        f"static const int ROSIE_PIN_PWMB = {_c_int(pins.get('pwmB'))};",
        f"static const int ROSIE_PIN_BIN1 = {_c_int(pins.get('bin1'))};",
        f"static const int ROSIE_PIN_BIN2 = {_c_int(pins.get('bin2'))};",
        f"static const int ROSIE_PWM_FREQ = {_c_int(pwm.get('freq', 20000))};",
        f"static const int ROSIE_PWM_RES = {_c_int(pwm.get('res', 8))};",
        f"static const float ROSIE_MIN_PWM = {_c_float(pwm.get('min', 55))};",
        f"static const float ROSIE_MAX_PWM = {_c_float(pwm.get('max', 100))};",
        "",
        f"static const int ROSIE_ENC_LA = {_c_int(left[0] if len(left) > 0 else 0)};",
        f"static const int ROSIE_ENC_LB = {_c_int(left[1] if len(left) > 1 else 0)};",
        f"static const int ROSIE_ENC_RA = {_c_int(right[0] if len(right) > 0 else 0)};",
        f"static const int ROSIE_ENC_RB = {_c_int(right[1] if len(right) > 1 else 0)};",
        "",
        f"static const unsigned long ROSIE_DT_MS = {_c_int(control.get('dt_ms', 20))}UL;",
        f"static const float ROSIE_TELEOP_KV = {_c_float(teleop.get('kv', 180))};",
        f"static const float ROSIE_TELEOP_KW = {_c_float(teleop.get('kw', 40))};",
        f"static const unsigned long ROSIE_TELEOP_TIMEOUT_MS = {_c_int(teleop.get('timeout_ms', 400))}UL;",
        f"static const float ROSIE_KP_LINEAR = {_c_float(goto.get('kp_linear', 0.8))};",
        f"static const float ROSIE_KP_ANGULAR = {_c_float(goto.get('kp_angular', 1.5))};",
        f"static const float ROSIE_V_MAX = {_c_float(goto.get('v_max', 0.35))};",
        f"static const float ROSIE_W_MAX = {_c_float(goto.get('w_max', 1.5))};",
        f"static const float ROSIE_POS_TOLERANCE = {_c_float(goto.get('pos_tolerance', 0.025))};",
        f"static const float ROSIE_APPROACH_DIST = {_c_float(goto.get('approach_dist', 0.20))};",
        f"static const float ROSIE_ALIGN_TOL = {_c_float(goto.get('align_tol', 0.52))};",
        f"static const float ROSIE_POSE_HZ = {_c_float(control.get('pose_hz', 20))};",
        f"static const float ROSIE_PRESENCE_HZ = {_c_float(control.get('presence_hz', 1))};",
        "",
        f"static const float ROSIE_VEL_KP = {_c_float(velocity.get('kp', 0.0))};",
        f"static const float ROSIE_VEL_KI = {_c_float(velocity.get('ki', 0.0))};",
        f"static const float ROSIE_VEL_KD = {_c_float(velocity.get('kd', 0.0))};",
        f"static const float ROSIE_VEL_ICLAMP = {_c_float(velocity.get('i_clamp', 0.5))};",
        "",
        f"static const int ROSIE_IMU_SDA = {_c_int(i2c.get('sda', 1))};",
        f"static const int ROSIE_IMU_SCL = {_c_int(i2c.get('scl', 2))};",
        f"static const uint8_t ROSIE_IMU_ADDR = {_c_int(i2c.get('addr', 0x68))};",
        f"static const int ROSIE_IMU_YAW_AXIS = {_c_int(imu.get('yaw_axis', 2))};",
        f"static const float ROSIE_IMU_YAW_SIGN = {_c_float(imu.get('yaw_sign', -1))};",
        "",
        f"static const int ROSIE_CAMERA_JPEG_QUALITY = {_c_int(cam.get('jpeg_quality', 18))};",
        f"static const float ROSIE_CAMERA_PUB_HZ = {_c_float(cam.get('pub_hz', 2))};",
        f"static const bool ROSIE_CAMERA_ENABLE_DEFAULT = {'true' if cam.get('enable_default', True) else 'false'};",
        f"static const bool ROSIE_HAS_CAMERA = {'true' if cam else 'false'};",
        f"static const bool ROSIE_HAS_IMU = {'true' if imu else 'false'};",
        "",
    ]
    return "\n".join(lines)


def write_robot_config_h(cfg: RobotConfig, project_dir: str | Path) -> Path:
    out_dir = Path(project_dir).expanduser().resolve() / "src" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "robot_config.h"
    out.write_text(generate_robot_config_h(cfg), encoding="utf-8")
    return out


def format_drivers_list(
    entries: list[DriverEntry] | None = None,
    *,
    category: str | None = None,
    platform: str | None = None,
) -> str:
    entries = entries or load_registry()
    lines = []
    cats: dict[str, list[DriverEntry]] = {}
    for e in entries:
        if category and e.category != category:
            continue
        if platform and platform not in e.platforms:
            continue
        cats.setdefault(e.category, []).append(e)
    for cat in sorted(cats):
        lines.append(f"[{cat}]")
        for e in cats[cat]:
            alias = f" (aliases: {', '.join(e.aliases)})" if e.aliases else ""
            plats = ",".join(e.platforms)
            lines.append(
                f"  {e.id:24} {e.status:10} [{plats:11}] {e.description}{alias}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
