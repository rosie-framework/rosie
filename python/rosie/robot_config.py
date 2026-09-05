"""Load / validate robot.yaml and generate firmware robot_config.h."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .connect import AUTO_CONNECT, SOFTAP_CONNECT, is_auto_connect

SUPPORTED_BASE = frozenset({"diff_drive"})
PLANNED_BASE = frozenset({"mecanum", "ackermann"})
SUPPORTED_VELOCITY = frozenset({"pid"})

# Canonical jpeg_quality is 0–100 (higher = better). MCU codegen translates
# to esp_camera's 0–63 scale (lower = better). Default 70 ≈ esp 19.
DEFAULT_JPEG_QUALITY = 70
MAX_RANGE_SENSORS = 4
RANGE_MEDIAN_WINDOW = 5
RANGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# proto/host:port — host may be a name or IPv4.
CONNECT_LOCATOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*/.+:\d+$")
VL53_RANGE_CHIPS = frozenset({"vl53l0x", "vl53l1x"})
# MCU codegen chip codes (must match DiffDriveStack).
RANGE_CHIP_VL53L1X = 0
RANGE_CHIP_VL53L0X = 1


def _is_vl53_chip(chip: str) -> bool:
    return chip in VL53_RANGE_CHIPS


def default_range_limits(chip: str) -> tuple[float, float]:
    """Return (min_range, max_range) meters for a chip when YAML omits them."""
    if chip == "vl53l0x":
        return 0.03, 2.0
    return 0.04, 4.0


def _default_range_limits(chip: str) -> tuple[float, float]:
    return default_range_limits(chip)


def _range_chip_code(chip: str) -> int:
    if chip == "vl53l0x":
        return RANGE_CHIP_VL53L0X
    return RANGE_CHIP_VL53L1X  # default / vl53l1x



def jpeg_quality_to_esp(q: float | int) -> int:
    """Map canonical 0–100 (higher better) → esp_camera 0–63 (lower better).

    Floors at 10: below that, esp_camera frames get huge and can fail to allocate.
    """
    qf = float(q)
    return max(10, min(63, round(63 - qf * 63 / 100)))



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
        + f". See `rosie drivers list` or docs/robots/drivers.md."
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
class ResolvedConnect:
    """How ``network.connect`` should be interpreted for a given consumer."""

    requested: str
    """Value host/Linux consumers should see (``auto`` or an explicit locator)."""
    locator: str
    """MCU firmware locator (``auto`` already resolved to a LAN IP)."""
    provenance: str
    candidates: list[str] = field(default_factory=list)


def _raw_connect(net: dict[str, Any]) -> str | None:
    raw = net.get("connect")
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def requested_connect(cfg: RobotConfig) -> str:
    """Connect string host/Linux consumers should see (never does LAN lookup)."""
    net = cfg.raw.get("network") or {}
    raw = _raw_connect(net)
    if raw is not None:
        validate_connect_value(raw)
        if not is_auto_connect(raw):
            return raw
    mode = str(net.get("mode", "softap")).strip().lower()
    if is_auto_connect(raw) or cfg.platform == "linux" or mode == "station":
        return AUTO_CONNECT
    return SOFTAP_CONNECT


def validate_connect_value(value: str) -> None:
    """Accept ``auto`` / ``scout`` or ``<proto>/<host>:<port>``."""
    if is_auto_connect(value):
        return
    if CONNECT_LOCATOR_RE.match(value):
        return
    raise ValueError(
        f"robot.yaml: network.connect must be 'auto' or "
        f"<proto>/<host>:<port> (got {value!r})"
    )


def resolve_robot_connect(
    cfg: RobotConfig,
    *,
    override: str | None = None,
    lan_ips: list[str] | None = None,
) -> ResolvedConnect:
    """Resolve ``network.connect`` for MCU codegen and host/Linux consumers.

    Explicit locators always win. ``auto`` (or omitted station / linux) stays
    ``auto`` for Linux/host; MCU codegen bakes the router-host LAN IP.
    Omitted SoftAP stays ``tcp/192.168.4.2:7447``.
    """
    from .netinfo import lan_locator, local_ipv4s

    if override is not None and str(override).strip():
        ov = str(override).strip()
        validate_connect_value(ov)
        if not is_auto_connect(ov):
            return ResolvedConnect(
                requested=ov, locator=ov, provenance="cli --connect"
            )

    requested = requested_connect(cfg)
    if not is_auto_connect(requested):
        raw = _raw_connect(cfg.raw.get("network") or {})
        provenance = "robot.yaml" if raw else "softap default"
        return ResolvedConnect(
            requested=requested, locator=requested, provenance=provenance
        )

    ips = list(lan_ips) if lan_ips is not None else local_ipv4s()
    if not ips:
        raise ValueError(
            "network.connect is auto but no LAN IPv4 was detected. "
            "Pass --connect tcp/<router-host-ip>:7447 or join a network."
        )
    locator = lan_locator(ips[0])
    others = [lan_locator(ip) for ip in ips[1:]]
    return ResolvedConnect(
        requested=AUTO_CONNECT,
        locator=locator,
        provenance=f"auto → {ips[0]}",
        candidates=others,
    )


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
        """Unresolved connect string for host / Linux consumers.

        ``auto`` is returned as-is (Linux scouts; host tools treat it as
        unset). Omitted station / linux defaults to ``auto``; omitted SoftAP
        stays ``tcp/192.168.4.2:7447``.
        """
        return requested_connect(self)

    @property
    def network_mode(self) -> str:
        return str(self.raw.get("network", {}).get("mode", "softap"))

    @property
    def fleet_secret(self) -> str | None:
        net = self.raw.get("network") or {}
        s = net.get("fleet_secret") or net.get("zenoh_password")
        if s is None or s == "":
            return None
        return str(s)

    @property
    def zenoh_user(self) -> str | None:
        net = self.raw.get("network") or {}
        u = net.get("user") or net.get("zenoh_user")
        if u is None or u == "":
            if self.fleet:
                return self.fleet
            return None
        return str(u)

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
    fleet = raw.get("fleet")
    if fleet is None or fleet is False or not str(fleet).strip():
        raise ValueError("robot.yaml: missing required field 'fleet'")
    entries = registry if registry is not None else load_registry()

    platform = str(raw.get("platform", "mcu") or "mcu").strip().lower()
    if platform not in ("mcu", "linux"):
        raise ValueError(
            f"robot.yaml: platform must be 'mcu' or 'linux' (got {platform!r})"
        )

    net = raw.get("network") or {}
    connect = net.get("connect")
    if connect is not None and str(connect).strip():
        validate_connect_value(str(connect).strip())

    if platform == "mcu":
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
        if platform == "mcu" and drv == "l298n":
            pins = motors.get("pins") or {}
            for key in ("ena", "in1", "in2", "enb", "in3", "in4"):
                if key not in pins:
                    raise ValueError(
                        f"robot.yaml: motors.driver=l298n requires motors.pins.{key}"
                    )
        if platform == "mcu" and drv == "tb6612":
            pins = motors.get("pins") or {}
            for key in ("pwmA", "ain1", "ain2", "pwmB", "bin1", "bin2"):
                if key not in pins:
                    raise ValueError(
                        f"robot.yaml: motors.driver=tb6612 requires motors.pins.{key}"
                    )
        pwm = motors.get("pwm") or {}
        if "min" in pwm or "max" in pwm:
            try:
                pmin = float(pwm.get("min", 0.1))
                pmax = float(pwm.get("max", 1.0))
            except (TypeError, ValueError) as e:
                raise ValueError(
                    "robot.yaml: motors.pwm.min and motors.pwm.max must be numbers"
                ) from e
            if not 0.0 <= pmin <= 1.0 or not 0.0 <= pmax <= 1.0:
                raise ValueError(
                    "robot.yaml: motors.pwm.min and motors.pwm.max must be in [0, 1] "
                    "(fraction of full PWM; res sets timer bits)"
                )
            if pmin > pmax:
                raise ValueError(
                    "robot.yaml: motors.pwm.min must be <= motors.pwm.max"
                )
    elif platform == "linux":
        raise ValueError("robot.yaml: motors section required for platform: linux")

    enc = raw.get("encoders")
    if enc:
        if platform == "linux":
            edrv = str(enc.get("driver", "gpio_quadrature"))
        else:
            edrv = str(enc.get("driver", "quad_encoder"))
        edrv = _resolve_id(edrv, entries, "encoders")
        _require_supported(entries, edrv, "encoders", platform=platform)
        if platform == "linux" and edrv == "python" and not enc.get("class"):
            raise ValueError("encoders.driver=python requires encoders.class")
        if "pub_hz" in enc:
            try:
                ehz = float(enc["pub_hz"])
            except (TypeError, ValueError) as e:
                raise ValueError("robot.yaml: encoders.pub_hz must be a number") from e
            if ehz < 0:
                raise ValueError("robot.yaml: encoders.pub_hz must be >= 0")

    imu = raw.get("imu")
    if imu:
        chip = str(imu.get("chip", "mpu6050"))
        chip = _resolve_id(chip, entries, "imu")
        _require_supported(entries, chip, "imu", platform=platform)
        if platform == "linux" and chip == "python" and not imu.get("class"):
            raise ValueError("imu.chip=python requires imu.class")
        if "pub_hz" in imu:
            try:
                ihz = float(imu["pub_hz"])
            except (TypeError, ValueError) as e:
                raise ValueError("robot.yaml: imu.pub_hz must be a number") from e
            if ihz < 0:
                raise ValueError("robot.yaml: imu.pub_hz must be >= 0")

    cam = raw.get("camera")
    if cam:
        if not isinstance(cam, dict):
            raise ValueError("robot.yaml: camera must be a mapping")
        if "jpeg_quality" in cam:
            try:
                jq = float(cam["jpeg_quality"])
            except (TypeError, ValueError) as e:
                raise ValueError(
                    "robot.yaml: camera.jpeg_quality must be a number"
                ) from e
            if jq < 0 or jq > 100:
                raise ValueError(
                    "robot.yaml: camera.jpeg_quality must be in 0..100 "
                    "(higher = better quality; MCU codegen maps to esp_camera)"
                )
        if "pub_hz" in cam:
            try:
                chz = float(cam["pub_hz"])
            except (TypeError, ValueError) as e:
                raise ValueError("robot.yaml: camera.pub_hz must be a number") from e
            if chz < 0:
                raise ValueError("robot.yaml: camera.pub_hz must be >= 0")
        if platform == "linux":
            drv = str(cam.get("driver", "picamera2"))
            drv = _resolve_id(drv, entries, "camera")
            _require_supported(entries, drv, "camera", platform=platform)
            if drv == "python" and not cam.get("class"):
                raise ValueError("camera.driver=python requires camera.class")
            for key in ("width", "height"):
                if key in cam:
                    try:
                        dim = int(cam[key])
                    except (TypeError, ValueError) as e:
                        raise ValueError(
                            f"robot.yaml: camera.{key} must be an integer"
                        ) from e
                    if dim <= 0:
                        raise ValueError(f"robot.yaml: camera.{key} must be > 0")
        else:
            board = str(cam.get("board", "esp32s3_eye"))
            board = _resolve_id(board, entries, "camera")
            _require_supported(entries, board, "camera", platform=platform)
            if board == "custom":
                pins = cam.get("pins")
                if not isinstance(pins, dict) or not pins:
                    raise ValueError(
                        "robot.yaml: camera.board=custom requires camera.pins mapping"
                    )

    _validate_range_section(raw, entries, platform=platform)

    control = raw.get("control") or {}
    teleop = control.get("teleop") or {}
    if teleop:
        if not isinstance(teleop, dict):
            raise ValueError("robot.yaml: control.teleop must be a mapping")
        if "k_ff" in teleop:
            raise ValueError(
                "robot.yaml: control.teleop.k_ff was removed; use "
                "control.teleop.v_full (wheel m/s at |channel|=1)"
            )
        if "v_full" in teleop:
            try:
                v_full = float(teleop["v_full"])
            except (TypeError, ValueError) as e:
                raise ValueError(
                    "robot.yaml: control.teleop.v_full must be a number"
                ) from e
            if v_full <= 0:
                raise ValueError("robot.yaml: control.teleop.v_full must be > 0")
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


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def normalize_range_sensors(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return per-sensor configs with shared range: defaults merged in.

    Each item has ``id`` plus the sensor mapping fields (chip, i2c, …).
    """
    section = raw.get("range")
    if not section:
        return []
    if not isinstance(section, dict):
        raise ValueError("robot.yaml: range must be a mapping")
    sensors = section.get("sensors")
    if not isinstance(sensors, dict) or not sensors:
        raise ValueError("robot.yaml: range.sensors must be a non-empty mapping")

    shared = {k: v for k, v in section.items() if k != "sensors"}
    out: list[dict[str, Any]] = []
    for sid, cfg in sensors.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"robot.yaml: range.sensors.{sid} must be a mapping")
        merged = _deep_merge_dict(shared, cfg)
        merged["id"] = str(sid)
        out.append(merged)
    return out


def _validate_range_section(
    raw: dict[str, Any],
    entries: list[DriverEntry],
    *,
    platform: str,
) -> None:
    if not raw.get("range"):
        return
    sensors = normalize_range_sensors(raw)
    if len(sensors) > MAX_RANGE_SENSORS:
        raise ValueError(
            f"robot.yaml: range.sensors supports at most {MAX_RANGE_SENSORS} "
            f"sensors (got {len(sensors)})"
        )

    seen_ids: set[str] = set()
    vl53_count = 0
    addrs: list[int] = []
    for sens in sensors:
        sid = sens["id"]
        if not RANGE_ID_RE.match(sid):
            raise ValueError(
                f"robot.yaml: range sensor id {sid!r} must match [A-Za-z0-9_-]+"
            )
        if sid in seen_ids:
            raise ValueError(f"robot.yaml: duplicate range sensor id {sid!r}")
        seen_ids.add(sid)

        chip = str(sens.get("chip", "vl53l1x"))
        chip = _resolve_id(chip, entries, "range")
        _require_supported(entries, chip, "range", platform=platform)
        if platform == "linux" and chip == "python" and not sens.get("class"):
            raise ValueError(
                f"range.sensors.{sid}: chip=python requires class"
            )

        if "pub_hz" in sens:
            try:
                hz = float(sens["pub_hz"])
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"robot.yaml: range.sensors.{sid}.pub_hz must be a number"
                ) from e
            if hz < 0:
                raise ValueError(
                    f"robot.yaml: range.sensors.{sid}.pub_hz must be >= 0"
                )

        for key in ("min_range", "max_range"):
            if key in sens:
                try:
                    float(sens[key])
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"robot.yaml: range.sensors.{sid}.{key} must be a number"
                    ) from e

        if _is_vl53_chip(chip):
            vl53_count += 1
            i2c = sens.get("i2c") or {}
            if not isinstance(i2c, dict):
                raise ValueError(
                    f"robot.yaml: range.sensors.{sid}.i2c must be a mapping"
                )
            addr = i2c.get("addr", 0x29)
            try:
                addrs.append(int(addr))
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"robot.yaml: range.sensors.{sid}.i2c.addr must be an int"
                ) from e

    if vl53_count > 1:
        for sens in sensors:
            chip = _resolve_id(str(sens.get("chip", "vl53l1x")), entries, "range")
            if not _is_vl53_chip(chip):
                continue
            if sens.get("xshut") is None:
                raise ValueError(
                    f"robot.yaml: range.sensors.{sens['id']} requires xshut "
                    "when multiple VL53 sensors share a bus"
                )
        if len(addrs) != len(set(addrs)):
            raise ValueError(
                "robot.yaml: range.sensors VL53 I2C addresses must be unique"
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


def generate_robot_config_h(
    cfg: RobotConfig,
    *,
    connect_override: str | None = None,
    lan_ips: list[str] | None = None,
) -> str:
    """Emit C++ header with constants for the robot firmware."""
    if cfg.platform == "linux":
        raise ValueError(
            "generate_robot_config_h is MCU-only; "
            "platform: linux uses `rosie run` (no codegen)."
        )
    r = cfg.raw
    net = r.get("network") or {}
    resolved = resolve_robot_connect(
        cfg, override=connect_override, lan_ips=lan_ips
    )
    base = r.get("base") or {}
    motors = r.get("motors") or {}
    motor_drv = str(motors.get("driver", "tb6612"))
    pins = motors.get("pins") or {}
    pwm = motors.get("pwm") or {}
    enc_section = r.get("encoders") or {}
    has_encoders = bool(r.get("encoders"))
    enc_drv = str(enc_section.get("driver", "quad_encoder")) if has_encoders else ""
    enc = enc_section.get("pins") or {}
    left = enc.get("left") or [0, 0]
    right = enc.get("right") or [0, 0]
    control = r.get("control") or {}
    teleop = control.get("teleop") or {}
    goto = control.get("goto") or {}
    velocity = control.get("velocity") or {}
    imu = r.get("imu") or {}
    has_imu = bool(r.get("imu"))
    imu_chip = str(imu.get("chip", "mpu6050")) if has_imu else ""
    i2c = imu.get("i2c") or {}
    cam = r.get("camera") or {}
    has_camera = bool(r.get("camera"))
    cam_board = str(cam.get("board", "esp32s3_eye")) if has_camera else ""
    cam_pins = cam.get("pins") or {}

    fleet = cfg.fleet
    if not fleet:
        raise ValueError("robot.yaml: missing required field 'fleet'")
    fleet_line = f"static const char* ROSIE_FLEET_ID = {_c_str(fleet)};"

    extra_connect = ""
    if resolved.candidates:
        extra_connect = "; other LAN: " + ", ".join(resolved.candidates)
    lines = [
        "// AUTO-GENERATED by `rosie mcu gen-config` — do not edit by hand.",
        "// Source: robot.yaml",
        f"// Zenoh connect: {resolved.locator} ({resolved.provenance}{extra_connect})",
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
        f"static const char* ROSIE_ZENOH_CONNECT = {_c_str(resolved.locator)};",
        f"static const char* ROSIE_ZENOH_MODE = {_c_str(str(net.get('zenoh_mode', 'client')))};",
    ]
    # Auth (optional): emit SHA-256 hex of fleet_secret to match host zenoh usrpwd hashing.
    secret = cfg.fleet_secret
    user = cfg.zenoh_user
    if secret and user:
        from .auth import sha256_hex

        lines.extend(
            [
                f"static const char* ROSIE_ZENOH_USER = {_c_str(user)};",
                f"static const char* ROSIE_ZENOH_PASSWORD = {_c_str(sha256_hex(secret))};",
            ]
        )
    else:
        lines.extend(
            [
                "static const char* ROSIE_ZENOH_USER = nullptr;",
                "static const char* ROSIE_ZENOH_PASSWORD = nullptr;",
            ]
        )

    lines += [
        "",
        f"static const float ROSIE_WHEEL_DIAMETER = {_c_float(base.get('wheel_diameter', 0.068))};",
        f"static const float ROSIE_WHEEL_BASE = {_c_float(base.get('wheel_base', 0.13))};",
        f"static const float ROSIE_TICKS_PER_REV = {_c_float(base.get('ticks_per_rev', 1440))};",
        "",
        f"static const char* ROSIE_MOTORS_DRIVER = {_c_str(motor_drv)};",
    ]

    if motor_drv == "l298n":
        lines += [
            "#define ROSIE_MOTORS_L298N 1",
            f"#define ROSIE_MOTORS_DRIVER_ID {_c_str(motor_drv)}",
            f"static const int ROSIE_PIN_ENA = {_c_int(pins.get('ena'))};",
            f"static const int ROSIE_PIN_IN1 = {_c_int(pins.get('in1'))};",
            f"static const int ROSIE_PIN_IN2 = {_c_int(pins.get('in2'))};",
            f"static const int ROSIE_PIN_ENB = {_c_int(pins.get('enb'))};",
            f"static const int ROSIE_PIN_IN3 = {_c_int(pins.get('in3'))};",
            f"static const int ROSIE_PIN_IN4 = {_c_int(pins.get('in4'))};",
        ]
    else:
        # Default / tb6612
        lines += [
            "#define ROSIE_MOTORS_TB6612 1",
            f"#define ROSIE_MOTORS_DRIVER_ID {_c_str(motor_drv)}",
            f"static const int ROSIE_PIN_PWMA = {_c_int(pins.get('pwmA'))};",
            f"static const int ROSIE_PIN_AIN1 = {_c_int(pins.get('ain1'))};",
            f"static const int ROSIE_PIN_AIN2 = {_c_int(pins.get('ain2'))};",
            f"static const int ROSIE_PIN_PWMB = {_c_int(pins.get('pwmB'))};",
            f"static const int ROSIE_PIN_BIN1 = {_c_int(pins.get('bin1'))};",
            f"static const int ROSIE_PIN_BIN2 = {_c_int(pins.get('bin2'))};",
        ]

    lines += [
        f"static const int ROSIE_PWM_FREQ = {_c_int(pwm.get('freq', 20000))};",
        f"static const int ROSIE_PWM_RES = {_c_int(pwm.get('res', 8))};",
        f"static const float ROSIE_MIN_PWM = {_c_float(pwm.get('min', 0.1))};",
        f"static const float ROSIE_MAX_PWM = {_c_float(pwm.get('max', 1.0))};",
        "",
        f"#define ROSIE_HAS_ENCODERS {1 if has_encoders else 0}",
    ]
    if has_encoders:
        if enc_drv == "quad_encoder":
            lines.append("#define ROSIE_ENCODERS_QUAD_ENCODER 1")
        lines += [
            f"static const char* ROSIE_ENCODERS_DRIVER = {_c_str(enc_drv)};",
            f"static const int ROSIE_ENC_LA = {_c_int(left[0] if len(left) > 0 else 0)};",
            f"static const int ROSIE_ENC_LB = {_c_int(left[1] if len(left) > 1 else 0)};",
            f"static const int ROSIE_ENC_RA = {_c_int(right[0] if len(right) > 0 else 0)};",
            f"static const int ROSIE_ENC_RB = {_c_int(right[1] if len(right) > 1 else 0)};",
            f"static const float ROSIE_ENCODERS_PUB_HZ = {_c_float(enc_section.get('pub_hz', 0))};",
        ]
    else:
        lines += [
            "static const char* ROSIE_ENCODERS_DRIVER = nullptr;",
            "static const int ROSIE_ENC_LA = 0;",
            "static const int ROSIE_ENC_LB = 0;",
            "static const int ROSIE_ENC_RA = 0;",
            "static const int ROSIE_ENC_RB = 0;",
            "static const float ROSIE_ENCODERS_PUB_HZ = 0.0f;",
        ]

    lines += [
        "",
        f"static const unsigned long ROSIE_DT_MS = {_c_int(control.get('dt_ms', 20))}UL;",
        f"static const float ROSIE_TELEOP_V_FULL = {_c_float(teleop.get('v_full', 1.0))};",
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
        f"static const float ROSIE_CONTROL_HZ = {_c_float(control.get('control_hz', 5))};",
        "",
        f"static const float ROSIE_VEL_KP = {_c_float(velocity.get('kp', 0.0))};",
        f"static const float ROSIE_VEL_KI = {_c_float(velocity.get('ki', 0.0))};",
        f"static const float ROSIE_VEL_KD = {_c_float(velocity.get('kd', 0.0))};",
        f"static const float ROSIE_VEL_ICLAMP = {_c_float(velocity.get('i_clamp', 0.5))};",
        "",
        f"#define ROSIE_HAS_IMU {1 if has_imu else 0}",
    ]
    if has_imu:
        if imu_chip == "mpu6050":
            lines.append("#define ROSIE_IMU_MPU6050 1")
        lines += [
            f"static const char* ROSIE_IMU_CHIP = {_c_str(imu_chip)};",
            f"static const int ROSIE_IMU_SDA = {_c_int(i2c.get('sda', 1))};",
            f"static const int ROSIE_IMU_SCL = {_c_int(i2c.get('scl', 2))};",
            f"static const uint8_t ROSIE_IMU_ADDR = {_c_int(i2c.get('addr', 0x68))};",
            f"static const int ROSIE_IMU_YAW_AXIS = {_c_int(imu.get('yaw_axis', 2))};",
            f"static const float ROSIE_IMU_YAW_SIGN = {_c_float(imu.get('yaw_sign', -1))};",
            f"static const float ROSIE_IMU_PUB_HZ = {_c_float(imu.get('pub_hz', 0))};",
        ]
    else:
        lines += [
            "static const char* ROSIE_IMU_CHIP = nullptr;",
            "static const int ROSIE_IMU_SDA = 0;",
            "static const int ROSIE_IMU_SCL = 0;",
            "static const uint8_t ROSIE_IMU_ADDR = 0;",
            "static const int ROSIE_IMU_YAW_AXIS = 2;",
            "static const float ROSIE_IMU_YAW_SIGN = -1.0f;",
            "static const float ROSIE_IMU_PUB_HZ = 0.0f;",
        ]

    jpeg_q = cam.get("jpeg_quality", DEFAULT_JPEG_QUALITY)
    try:
        jpeg_q_f = float(jpeg_q)
    except (TypeError, ValueError):
        jpeg_q_f = float(DEFAULT_JPEG_QUALITY)
    esp_jpeg_q = jpeg_quality_to_esp(jpeg_q_f)

    lines += [
        "",
        f"#define ROSIE_HAS_CAMERA {1 if has_camera else 0}",
        # Canonical yaml is 0–100 higher-better; esp_camera wants 0–63 lower-better.
        f"static const int ROSIE_CAMERA_JPEG_QUALITY = {esp_jpeg_q};",
        f"static const float ROSIE_CAMERA_PUB_HZ = {_c_float(cam.get('pub_hz', 2))};",
        f"static const bool ROSIE_CAMERA_ENABLE_DEFAULT = {'true' if cam.get('enable_default', True) else 'false'};",
    ]
    if has_camera:
        lines.append(f"static const char* ROSIE_CAMERA_BOARD = {_c_str(cam_board)};")
        if cam_board in ("esp32s3_eye", "freenove_esp32s3_cam"):
            lines.append("#define ROSIE_CAMERA_ESP32S3_EYE 1")
        elif cam_board == "custom":
            lines += [
                "#define ROSIE_CAMERA_CUSTOM 1",
                f"static const int ROSIE_CAM_PWDN = {_c_int(cam_pins.get('pwdn', -1))};",
                f"static const int ROSIE_CAM_RESET = {_c_int(cam_pins.get('reset', -1))};",
                f"static const int ROSIE_CAM_XCLK = {_c_int(cam_pins.get('xclk'))};",
                f"static const int ROSIE_CAM_SIOD = {_c_int(cam_pins.get('siod'))};",
                f"static const int ROSIE_CAM_SIOC = {_c_int(cam_pins.get('sioc'))};",
                f"static const int ROSIE_CAM_Y9 = {_c_int(cam_pins.get('y9'))};",
                f"static const int ROSIE_CAM_Y8 = {_c_int(cam_pins.get('y8'))};",
                f"static const int ROSIE_CAM_Y7 = {_c_int(cam_pins.get('y7'))};",
                f"static const int ROSIE_CAM_Y6 = {_c_int(cam_pins.get('y6'))};",
                f"static const int ROSIE_CAM_Y5 = {_c_int(cam_pins.get('y5'))};",
                f"static const int ROSIE_CAM_Y4 = {_c_int(cam_pins.get('y4'))};",
                f"static const int ROSIE_CAM_Y3 = {_c_int(cam_pins.get('y3'))};",
                f"static const int ROSIE_CAM_Y2 = {_c_int(cam_pins.get('y2'))};",
                f"static const int ROSIE_CAM_VSYNC = {_c_int(cam_pins.get('vsync'))};",
                f"static const int ROSIE_CAM_HREF = {_c_int(cam_pins.get('href'))};",
                f"static const int ROSIE_CAM_PCLK = {_c_int(cam_pins.get('pclk'))};",
            ]
    else:
        lines.append("static const char* ROSIE_CAMERA_BOARD = nullptr;")

    # --- range / ToF -------------------------------------------------
    range_sensors: list[dict[str, Any]] = []
    try:
        range_sensors = normalize_range_sensors(r) if r.get("range") else []
    except ValueError:
        range_sensors = []
    has_range = bool(range_sensors)
    lines += [
        "",
        f"#define ROSIE_HAS_RANGE {1 if has_range else 0}",
        f"#define ROSIE_MAX_RANGE_SENSORS {MAX_RANGE_SENSORS}",
        f"#define ROSIE_RANGE_MEDIAN_WINDOW {RANGE_MEDIAN_WINDOW}",
        f"static const int ROSIE_RANGE_COUNT = {len(range_sensors)};",
    ]
    if has_range:
        # Shared bus pins: first sensor's i2c, else top-level range.i2c, else IMU defaults.
        top_i2c = (r.get("range") or {}).get("i2c") or {}
        first_i2c = (range_sensors[0].get("i2c") or {}) if range_sensors else {}
        sda = first_i2c.get("sda", top_i2c.get("sda", 1))
        scl = first_i2c.get("scl", top_i2c.get("scl", 2))
        chips_used = {
            str(s.get("chip", "vl53l1x")).lower() for s in range_sensors
        }
        lines += [
            f"static const int ROSIE_RANGE_SDA = {_c_int(sda)};",
            f"static const int ROSIE_RANGE_SCL = {_c_int(scl)};",
            f"#define ROSIE_RANGE_CHIP_VL53L1X {RANGE_CHIP_VL53L1X}",
            f"#define ROSIE_RANGE_CHIP_VL53L0X {RANGE_CHIP_VL53L0X}",
            f"#define ROSIE_RANGE_VL53L1X {1 if 'vl53l1x' in chips_used else 0}",
            f"#define ROSIE_RANGE_VL53L0X {1 if 'vl53l0x' in chips_used else 0}",
        ]
        ids = []
        addrs = []
        xshuts = []
        pub_hzs = []
        mins = []
        maxs = []
        chips = []
        for i in range(MAX_RANGE_SENSORS):
            if i < len(range_sensors):
                sens = range_sensors[i]
                chip = str(sens.get("chip", "vl53l1x")).lower()
                dmin, dmax = _default_range_limits(chip)
                i2c = sens.get("i2c") or {}
                ids.append(_c_str(str(sens["id"])))
                addrs.append(_c_int(i2c.get("addr", 0x29)))
                xshuts.append(_c_int(sens.get("xshut", -1)))
                pub_hzs.append(_c_float(sens.get("pub_hz", 10)))
                mins.append(_c_float(sens.get("min_range", dmin)))
                maxs.append(_c_float(sens.get("max_range", dmax)))
                chips.append(str(_range_chip_code(chip)))
            else:
                ids.append("nullptr")
                addrs.append("0")
                xshuts.append("-1")
                pub_hzs.append("0.0f")
                mins.append("0.04f")
                maxs.append("4.0f")
                chips.append(str(RANGE_CHIP_VL53L1X))
        lines += [
            "static const char* const ROSIE_RANGE_IDS[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(ids)
            + "};",
            "static const uint8_t ROSIE_RANGE_ADDRS[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(addrs)
            + "};",
            "static const int ROSIE_RANGE_XSHUTS[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(xshuts)
            + "};",
            "static const float ROSIE_RANGE_PUB_HZ[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(pub_hzs)
            + "};",
            "static const float ROSIE_RANGE_MIN_M[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(mins)
            + "};",
            "static const float ROSIE_RANGE_MAX_M[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(maxs)
            + "};",
            "static const uint8_t ROSIE_RANGE_CHIPS[ROSIE_MAX_RANGE_SENSORS] = {"
            + ", ".join(chips)
            + "};",
        ]
    else:
        lines += [
            "static const int ROSIE_RANGE_SDA = 0;",
            "static const int ROSIE_RANGE_SCL = 0;",
            f"#define ROSIE_RANGE_CHIP_VL53L1X {RANGE_CHIP_VL53L1X}",
            f"#define ROSIE_RANGE_CHIP_VL53L0X {RANGE_CHIP_VL53L0X}",
            "#define ROSIE_RANGE_VL53L1X 0",
            "#define ROSIE_RANGE_VL53L0X 0",
            "static const char* const ROSIE_RANGE_IDS[ROSIE_MAX_RANGE_SENSORS] = "
            "{nullptr, nullptr, nullptr, nullptr};",
            "static const uint8_t ROSIE_RANGE_ADDRS[ROSIE_MAX_RANGE_SENSORS] = "
            "{0, 0, 0, 0};",
            "static const int ROSIE_RANGE_XSHUTS[ROSIE_MAX_RANGE_SENSORS] = "
            "{-1, -1, -1, -1};",
            "static const float ROSIE_RANGE_PUB_HZ[ROSIE_MAX_RANGE_SENSORS] = "
            "{0.0f, 0.0f, 0.0f, 0.0f};",
            "static const float ROSIE_RANGE_MIN_M[ROSIE_MAX_RANGE_SENSORS] = "
            "{0.04f, 0.04f, 0.04f, 0.04f};",
            "static const float ROSIE_RANGE_MAX_M[ROSIE_MAX_RANGE_SENSORS] = "
            "{4.0f, 4.0f, 4.0f, 4.0f};",
            "static const uint8_t ROSIE_RANGE_CHIPS[ROSIE_MAX_RANGE_SENSORS] = "
            "{0, 0, 0, 0};",
        ]

    lines.append("")
    return "\n".join(lines)


def write_robot_config_h(
    cfg: RobotConfig,
    project_dir: str | Path,
    *,
    connect_override: str | None = None,
    lan_ips: list[str] | None = None,
) -> Path:
    resolved = resolve_robot_connect(
        cfg, override=connect_override, lan_ips=lan_ips
    )
    print(f"  Zenoh connect: {resolved.locator} ({resolved.provenance})")
    if resolved.candidates:
        print("  other LAN candidates: " + ", ".join(resolved.candidates))
    out_dir = Path(project_dir).expanduser().resolve() / "src" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "robot_config.h"
    out.write_text(
        generate_robot_config_h(
            cfg, connect_override=connect_override, lan_ips=lan_ips
        ),
        encoding="utf-8",
    )
    return out


def warn_jpeg_quality_scale(cfg: RobotConfig) -> str | None:
    """Return a migration warning if jpeg_quality looks like the old esp scale."""
    cam = cfg.raw.get("camera") or {}
    if not cam or "jpeg_quality" not in cam:
        return None
    try:
        jq = float(cam["jpeg_quality"])
    except (TypeError, ValueError):
        return None
    if jq < 30:
        return (
            f"warning: camera.jpeg_quality={jq:g} looks like the old esp_camera "
            "scale (lower=better). Canonical scale is now 0–100 higher=better "
            f"(default {DEFAULT_JPEG_QUALITY}). Suggest ~70; codegen maps to "
            f"esp_camera={jpeg_quality_to_esp(jq)}."
        )
    return None


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
