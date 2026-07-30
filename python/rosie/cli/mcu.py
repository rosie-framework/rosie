"""MCU subcommands — PlatformIO wrap for ESP32 and other PIO boards.

Linux robots (Pi, Jetson, laptop) use host commands (`rosie setup`, Session),
not this group.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path


def _require_platformio() -> None:
    try:
        import platformio  # noqa: F401
    except ImportError as e:
        print(
            "error: PlatformIO is not installed.\n"
            '  Install the MCU extra:  pip install "rosie-framework[mcu]"\n'
            "  Then re-run this command.",
            file=sys.stderr,
        )
        raise SystemExit(2) from e


def _pio_cmd() -> list[str]:
    return [sys.executable, "-m", "platformio"]


def _strip_passthrough(extra: list[str] | None) -> list[str]:
    if not extra:
        return []
    if extra and extra[0] == "--":
        return list(extra[1:])
    return list(extra)


def _autodetect_port() -> str | None:
    skip_substrings = ("bluetooth", "debug-console", "incoming-port")

    def usable(device: str, description: str = "") -> bool:
        blob = f"{device} {description}".lower()
        return not any(s in blob for s in skip_substrings)

    try:
        from serial.tools.list_ports import comports  # type: ignore

        ports = [p for p in comports() if usable(p.device, p.description or "")]
        preferred = [
            p.device
            for p in ports
            if "usb" in p.device.lower()
            or (p.description and "usb" in p.description.lower())
        ]
        if preferred:
            return preferred[0]
        if ports:
            return ports[0].device
    except Exception:
        pass
    for pat in ("/dev/cu.usb*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        matches = [m for m in sorted(glob.glob(pat)) if usable(m)]
        if matches:
            return matches[0]
    return None


def _prepare_firmware(project_dir: Path, *, link_project: bool = True) -> dict[str, str]:
    """Resolve Rosie firmware and return env updates for PlatformIO.

    Creates ``~/.rosie/pio_libs/rosie`` and optionally ``<project>/lib/rosie``.
    """
    from rosie.paths import ensure_pio_libs_link, ensure_project_lib_link, firmware_dir

    try:
        fw = firmware_dir()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2) from e

    pio_libs = ensure_pio_libs_link()
    print(f"Rosie firmware: {fw}")
    if link_project:
        link = ensure_project_lib_link(project_dir)
        print(f"Project lib link: {link} → {fw}")

    env = os.environ.copy()
    extra = str(pio_libs)
    prev = env.get("PLATFORMIO_LIB_EXTRA_DIRS", "").strip()
    if prev:
        parts = prev.split(os.pathsep)
        if extra not in parts:
            env["PLATFORMIO_LIB_EXTRA_DIRS"] = extra + os.pathsep + prev
    else:
        env["PLATFORMIO_LIB_EXTRA_DIRS"] = extra
    return env


def _run_pio(
    args: list[str],
    *,
    cwd: Path,
    extra: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    _require_platformio()
    cmd = _pio_cmd() + args + _strip_passthrough(extra)
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(cwd), env=env)


def _maybe_gen_config(project_dir: Path) -> None:
    """If robot.yaml exists, sync host secret when resolvable, then regenerate header."""
    from rosie.auth import maybe_sync_secret_for_robot_config
    from rosie.robot_config import (
        find_robot_yaml,
        load_robot_config,
        warn_jpeg_quality_scale,
        write_robot_config_h,
    )

    yml = find_robot_yaml(project_dir)
    if not yml:
        return
    try:
        cfg = load_robot_config(yml)
        if maybe_sync_secret_for_robot_config(yml, cfg.raw):
            print(f"Synced bus secret → {yml.name}")
            cfg = load_robot_config(yml)
        out = write_robot_config_h(cfg, project_dir)
        print(f"Generated {out} from {yml.name}")
        warn = warn_jpeg_quality_scale(cfg)
        if warn:
            print(warn, file=sys.stderr)
    except Exception as e:
        print(f"error: robot.yaml codegen failed: {e}", file=sys.stderr)
        raise SystemExit(2) from e


def cmd_gen_config(args: argparse.Namespace) -> int:
    cwd = Path(args.dir).expanduser().resolve()
    from rosie.auth import maybe_sync_secret_for_robot_config
    from rosie.robot_config import (
        find_robot_yaml,
        load_robot_config,
        warn_jpeg_quality_scale,
        write_robot_config_h,
    )

    yml = Path(args.file).expanduser().resolve() if args.file else find_robot_yaml(cwd)
    if not yml or not yml.is_file():
        print("error: no robot.yaml found (pass --file or place robot.yaml in project)", file=sys.stderr)
        return 2
    cfg = load_robot_config(yml)
    if maybe_sync_secret_for_robot_config(yml, cfg.raw):
        print(f"Synced bus secret → {yml.name}")
        cfg = load_robot_config(yml)
    out = write_robot_config_h(cfg, cwd)
    print(f"Wrote {out}")
    warn = warn_jpeg_quality_scale(cfg)
    if warn:
        print(warn, file=sys.stderr)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cwd = Path(args.dir).expanduser().resolve()
    env = _prepare_firmware(cwd)
    _maybe_gen_config(cwd)
    pio_args = ["run"]
    if args.env:
        pio_args.extend(["-e", args.env])
    return _run_pio(pio_args, cwd=cwd, extra=args.extra, env=env)


def cmd_flash(args: argparse.Namespace) -> int:
    cwd = Path(args.dir).expanduser().resolve()
    env = _prepare_firmware(cwd)
    _maybe_gen_config(cwd)
    pio_args = ["run", "-t", "upload"]
    if args.env:
        pio_args.extend(["-e", args.env])
    port = args.port or os.environ.get("ROSIE_PORT") or _autodetect_port()
    if port:
        pio_args.extend(["--upload-port", port])
        print(f"Using upload port: {port}")
    else:
        print(
            "warning: no serial port autodetected; "
            "PlatformIO may use platformio.ini upload_port",
            file=sys.stderr,
        )
    return _run_pio(pio_args, cwd=cwd, extra=args.extra, env=env)


def cmd_monitor(args: argparse.Namespace) -> int:
    cwd = Path(args.dir).expanduser().resolve()
    pio_args = ["device", "monitor"]
    port = args.port or os.environ.get("ROSIE_PORT") or _autodetect_port()
    if port:
        pio_args.extend(["--port", port])
        print(f"Using monitor port: {port}")
    if args.baud:
        pio_args.extend(["--baud", str(args.baud)])
    return _run_pio(pio_args, cwd=cwd, extra=args.extra)


def cmd_setup(args: argparse.Namespace) -> int:
    """Link Rosie firmware into the project, then warm PlatformIO packages."""
    cwd = Path(args.dir).expanduser().resolve()
    env = _prepare_firmware(cwd, link_project=True)
    _maybe_gen_config(cwd)
    _require_platformio()

    print("Installing PlatformIO packages for this project…")
    rc = _run_pio(["pkg", "install"], cwd=cwd, extra=None, env=env)
    if rc != 0:
        print("note: `pio pkg install` returned non-zero; continuing with warm build")

    print("Warm build (downloads toolchain + libs on first run)…")
    pio_args = ["run"]
    if args.env:
        pio_args.extend(["-e", args.env])
    return _run_pio(pio_args, cwd=cwd, extra=args.extra, env=env)


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold robot.yaml + thin DiffDriveStack main.cpp (+ optional platformio.ini)."""
    cwd = Path(args.dir).expanduser().resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    robot_id = args.robot or "mybot"

    yml_path = cwd / "robot.yaml"
    if yml_path.exists() and not args.force:
        print(f"error: {yml_path} exists (pass --force to overwrite)", file=sys.stderr)
        return 2

    yml = f"""robot: {robot_id}
fleet: null

network:
  mode: softap
  ssid: {robot_id}-AP
  password: rosie-robot
  connect: tcp/192.168.4.2:7447
  zenoh_mode: client

base:
  type: diff_drive
  wheel_diameter: 0.068
  wheel_base: 0.13
  ticks_per_rev: 1440

motors:
  driver: tb6612
  pins: {{ pwmA: 45, ain1: 42, ain2: 47, pwmB: 46, bin1: 48, bin2: 21 }}
  pwm: {{ freq: 20000, res: 8, min: 55, max: 100 }}

encoders:
  driver: quad_encoder
  pins: {{ left: [41, 38], right: [39, 40] }}
  # pub_hz: 10          # optional: publish EncoderTicks on encoders topic

control:
  dt_ms: 20
  teleop: {{ kv: 180, kw: 40, timeout_ms: 400, v_fwd: 0.25, v_turn: 1.2 }}
  # Outer loop: pose → Twist (m/s, rad/s)
  goto:
    kp_linear: 0.8
    kp_angular: 1.5
    v_max: 0.35
    w_max: 1.5
    pos_tolerance: 0.025
    approach_dist: 0.20
    align_tol: 0.52
  # Inner wheel-velocity PID; 0,0,0 = open-loop feedforward. Tune: rosie tune
  velocity:
    type: pid
    kp: 0.0
    ki: 0.0
    kd: 0.0
    i_clamp: 0.5
  pose_hz: 20
  presence_hz: 1
  # control_hz: 5        # optional: VelocityController telemetry rate

# Optional — uncomment / edit as needed:
# imu:
#   chip: mpu6050
#   i2c: {{ sda: 1, scl: 2, addr: 0x68 }}
#   yaw_axis: 2
#   yaw_sign: -1
#   pub_hz: 10          # optional: publish Imu on imu topic
# camera:
#   board: esp32s3_eye
#   # 0–100, higher = better. MCU codegen maps this to esp_camera's 0–63
#   # (lower = better) scale. Default 70 ≈ old esp default of 18.
#   jpeg_quality: 70
#   pub_hz: 2
#   enable_default: true
# range:
#   i2c: {{ sda: 1, scl: 2 }}   # shared bus (often same as IMU)
#   pub_hz: 10
#   min_range: 0.04
#   max_range: 4.0
#   sensors:
#     front:
#       chip: vl53l1x
#       i2c: {{ addr: 0x29 }}
#       # xshut: 7             # required when >1 VL53 on the bus
#     # front_right:
#     #   chip: vl53l0x       # also supported
#     #   i2c: {{ addr: 0x30 }}
#     #   xshut: 8
"""
    yml_path.write_text(yml, encoding="utf-8")
    print(f"Wrote {yml_path}")

    src = cwd / "src"
    src.mkdir(exist_ok=True)
    main_path = src / "main.cpp"
    if main_path.exists() and not args.force:
        print(f"note: {main_path} exists — not overwriting (use --force)")
    else:
        main_path.write_text(
            """#include <Arduino.h>

#include "generated/robot_config.h"
#include <rosie/diff_drive_stack.h>

// Edit robot.yaml, then: rosie mcu setup && rosie mcu flash
// Optional custom cmds: g_stack.base().onCmd("my_op", handler); before begin().

static rosie::DiffDriveStack g_stack;

void setup() {
  Serial.begin(115200);
  delay(300);
  g_stack.begin();
}

void loop() {
  g_stack.loop();
}
""",
            encoding="utf-8",
        )
        print(f"Wrote {main_path}")

    pio = cwd / "platformio.ini"
    if not pio.exists() or args.force:
        pio.write_text(
            f"""; Rosie DiffDriveStack robot — edit board/ports as needed.
; rosie mcu setup && rosie mcu flash

[env:esp32]
platform = espressif32
board = {args.board}
framework = arduino
monitor_speed = 115200

lib_ldf_mode = chain

build_flags =
    -DZENOH_COMPILER_GCC
    -DZENOH_ARDUINO_ESP32
    -DZ_FEATURE_MULTI_THREAD=1
    -DZ_FEATURE_PUBLICATION=1
    -DZ_FEATURE_SUBSCRIPTION=1

lib_deps =
    madhephaestus/ESP32Encoder
    bblanchon/ArduinoJson@^7.2.0
    https://github.com/eclipse-zenoh/zenoh-pico.git
""",
            encoding="utf-8",
        )
        print(f"Wrote {pio}")
    else:
        print(f"note: {pio} exists — not overwriting")

    _prepare_firmware(cwd, link_project=True)
    _maybe_gen_config(cwd)
    print()
    print("Next:")
    print(f"  1. Edit {yml_path.name} (pins, SSID, geometry)")
    print("  2. rosie mcu setup   # while online")
    print("  3. rosie mcu flash")
    print(f"  4. rosie drive --config {yml_path}")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    """Only create firmware links (no PlatformIO build)."""
    cwd = Path(args.dir).expanduser().resolve()
    _prepare_firmware(cwd, link_project=True)
    print("Firmware link ready.")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dir",
        default=".",
        help="PlatformIO project directory (default: cwd)",
    )
    p.add_argument(
        "--env",
        default=None,
        help="PlatformIO environment name (-e)",
    )
    p.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="extra args after -- passed to platformio",
    )


def register(sub: argparse._SubParsersAction) -> None:
    """Register ``rosie mcu {setup,link,build,flash,monitor,gen-config}``."""
    p_mcu = sub.add_parser(
        "mcu",
        help="MCU / PlatformIO robots (ESP32, …) — not for Pi/Jetson/laptop hosts",
    )
    mcu_sub = p_mcu.add_subparsers(dest="mcu_command")

    p_setup = mcu_sub.add_parser(
        "setup",
        help="link Rosie firmware + cache MCU toolchain/libs (while online)",
    )
    _add_common(p_setup)
    p_setup.set_defaults(func=cmd_setup)

    p_link = mcu_sub.add_parser(
        "link",
        help="create lib/rosie → Rosie firmware (no build)",
    )
    p_link.add_argument(
        "--dir",
        default=".",
        help="PlatformIO project directory (default: cwd)",
    )
    p_link.set_defaults(func=cmd_link)

    p_init = mcu_sub.add_parser(
        "init",
        help="scaffold robot.yaml + DiffDriveStack main.cpp (+ platformio.ini)",
    )
    p_init.add_argument("--dir", default=".", help="project directory (default: cwd)")
    p_init.add_argument("--robot", default="mybot", help="robot id (default: mybot)")
    p_init.add_argument(
        "--board",
        default="esp32-s3-devkitc-1",
        help="PlatformIO board id (default: esp32-s3-devkitc-1)",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing robot.yaml / main.cpp / platformio.ini",
    )
    p_init.set_defaults(func=cmd_init)

    p_gen = mcu_sub.add_parser(
        "gen-config",
        help="generate src/generated/robot_config.h from robot.yaml",
    )
    p_gen.add_argument("--dir", default=".", help="project directory (default: cwd)")
    p_gen.add_argument("--file", default=None, help="path to robot.yaml (optional)")
    p_gen.set_defaults(func=cmd_gen_config)

    p_build = mcu_sub.add_parser("build", help="build firmware (wraps `pio run`)")
    _add_common(p_build)
    p_build.set_defaults(func=cmd_build)

    p_flash = mcu_sub.add_parser(
        "flash", help="build + upload firmware (wraps `pio run -t upload`)"
    )
    _add_common(p_flash)
    p_flash.add_argument(
        "--port",
        default=None,
        help="serial port (default: autodetect or ROSIE_PORT)",
    )
    p_flash.set_defaults(func=cmd_flash)

    p_mon = mcu_sub.add_parser(
        "monitor", help="serial monitor (wraps `pio device monitor`)"
    )
    _add_common(p_mon)
    p_mon.add_argument(
        "--port",
        default=None,
        help="serial port (default: autodetect or ROSIE_PORT)",
    )
    p_mon.add_argument("--baud", type=int, default=None, help="baud rate")
    p_mon.set_defaults(func=cmd_monitor)
