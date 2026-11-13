"""``rosie robot`` — install the DDS bridge and the watchdog on a robot."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from rosie.profiles import PROFILES, bridge_config, load_profile


def _config_path(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config).expanduser().resolve()
    return Path.cwd() / "rosie-bridge.json5"


def cmd_setup(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    if profile.transport != "bridge":
        print(
            "error: rosie robot setup writes a zenoh-bridge-ros2dds config. "
            "rmw_zenoh robots do not use this bridge; launch them with "
            "RMW_IMPLEMENTATION=rmw_zenoh_cpp and a ROS namespace "
            f"/{args.fleet}/{args.robot}.",
            file=sys.stderr,
        )
        return 2
    connect = args.connect or os.environ.get("ROSIE_CONNECT") or "auto"
    cfg = bridge_config(
        profile,
        fleet=args.fleet,
        robot=args.robot,
        connect=connect if connect != "auto" else "tcp/127.0.0.1:7447",
        mode=args.mode,
    )
    cfg["rosie"] = {
        "fleet": args.fleet,
        "robot": args.robot,
        "profile": profile.name,
        "connect": connect,
        "mode": args.mode,
    }
    if args.secure:
        from rosie.auth import credentials_for, resolve_secret_plaintext, sha256_hex

        password = resolve_secret_plaintext(fleet=args.fleet, secure=True)
        creds = credentials_for(fleet=args.fleet, password=password)
        if creds is None:
            print("error: --secure set but no fleet secret was found", file=sys.stderr)
            return 1
        cfg.setdefault("transport", {}).setdefault("auth", {}).setdefault("usrpwd", {})
        cfg["transport"]["auth"]["usrpwd"]["user"] = creds.user
        cfg["transport"]["auth"]["usrpwd"]["password"] = sha256_hex(creds.password)

    path = _config_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")

    if args.no_download:
        bridge = args.bridge or "zenoh-bridge-ros2dds"
    else:
        from rosie.bootstrap import download_bridge

        try:
            bridge = str(download_bridge(triple=args.triple or None))
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    unit = _install_units(
        config=path,
        bridge=bridge,
        fleet=args.fleet,
        robot=args.robot,
        profile=profile.name,
        distro=profile.distro,
        secure=args.secure,
        connect=connect,
    )
    if unit:
        print(f"Wrote {unit}")
        print("Enable with: systemctl --user daemon-reload && systemctl --user enable --now rosie-bridge.service rosie-watchdog.service")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Resolve ``connect: auto``, then exec the bridge. Used by systemd."""
    path = _config_path(args)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    meta = cfg.get("rosie") or {}
    connect = str(meta.get("connect") or "auto")
    fleet = str(meta.get("fleet") or "")
    if connect == "auto":
        if not fleet:
            print("error: bridge config has connect auto but no fleet", file=sys.stderr)
            return 2
        from rosie.discovery import resolve_auto_connect

        connect = resolve_auto_connect(fleet)
        cfg.setdefault("connect", {})["endpoints"] = [connect]
    bridge = args.bridge or shutil.which("zenoh-bridge-ros2dds")
    if not bridge:
        from rosie.bootstrap import bridge_cache_path, detect_triple

        candidate = bridge_cache_path(args.triple or detect_triple())
        if candidate.is_file():
            bridge = str(candidate)
    if not bridge:
        print("error: zenoh-bridge-ros2dds not found. Run `rosie robot setup`.", file=sys.stderr)
        return 1
    # The bridge reads the file we just resolved. Rewrite beside the original
    # so a concurrent reader still sees valid JSON.
    runtime = path.with_suffix(".runtime.json5")
    runtime.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.execv(bridge, [bridge, "-c", str(runtime)])
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    path = _config_path(args)
    ok = True
    if not path.is_file():
        print(f"config: FAIL (missing {path})")
        return 1
    cfg = json.loads(path.read_text(encoding="utf-8"))
    meta = cfg.get("rosie") or {}
    ros = (cfg.get("plugins") or {}).get("ros2dds") or {}
    print(f"config:   {path}")
    print(f"fleet:    {meta.get('fleet', '—')}")
    print(f"robot:    {meta.get('robot', '—')}")
    print(f"profile:  {meta.get('profile', '—')}")
    print(f"mode:     {meta.get('mode', cfg.get('mode', '—'))}")
    print(f"connect:  {meta.get('connect', '—')}")
    namespace = ros.get("namespace")
    expect = None
    if meta.get("fleet") and meta.get("robot"):
        expect = f"/{meta['fleet']}/{meta['robot']}"
    if namespace and expect and namespace != expect:
        print(f"namespace: FAIL ({namespace}, expected {expect})")
        ok = False
    else:
        print(f"namespace: {namespace or '—'}")
    allow = ros.get("allow") or {}
    print(f"allow:    {', '.join(sorted(allow)) or 'all topics'}")
    if ok:
        print("doctor: config looks usable")
        print("On the robot, confirm the profile topics exist with: ros2 topic list")
        return 0
    print("doctor: fix the items above", file=sys.stderr)
    return 1


def service_exec(distro: str, argv: list[str]) -> str:
    """Shell line that sources the robot's ROS distro, then execs ``argv``.

    User systemd does not source ``/opt/ros``. The watchdog imports ``rclpy``
    from that environment, and the bridge needs the same ``ROS_DOMAIN_ID``.
    """
    setup = f"/opt/ros/{distro}/setup.bash"
    inner = " ".join(shlex.quote(part) for part in argv)
    return f"/bin/bash -lc 'source {shlex.quote(setup)} && exec {inner}'"


def _install_units(
    *,
    config: Path,
    bridge: str,
    fleet: str,
    robot: str,
    profile: str,
    distro: str,
    secure: bool,
    connect: str,
) -> Path | None:
    if not sys.platform.startswith("linux"):
        print("systemd units skipped (not Linux). Start the bridge with:")
        print(f"  rosie robot run --config {config}")
        return None
    if shutil.which("rosie"):
        rosie_argv = [shutil.which("rosie")]
    else:
        rosie_argv = [sys.executable, "-m", "rosie.cli"]
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    secure_flag = ["--secure"] if secure else []
    run_exec = service_exec(distro, [*rosie_argv, "robot", "run", "--config", str(config)])
    watch_exec = service_exec(
        distro,
        [
            *rosie_argv,
            "robot",
            "watchdog",
            "--fleet",
            fleet,
            "--robot",
            robot,
            "--profile",
            profile,
            "--config",
            str(config),
            *secure_flag,
        ],
    )
    bridge_unit = f"""[Unit]
Description=Rosie ROS 2 bridge ({fleet}/{robot})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={run_exec}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""
    watch_unit = f"""[Unit]
Description=Rosie watchdog ({fleet}/{robot})
After=network-online.target rosie-bridge.service
Wants=rosie-bridge.service

[Service]
Type=simple
ExecStart={watch_exec}
Restart=on-failure
RestartSec=2
Environment=ROSIE_FLEET={fleet}
Environment=ROSIE_ROBOT={robot}

[Install]
WantedBy=default.target
"""
    # connect is resolved by `rosie robot run`, not baked here.
    del connect
    (unit_dir / "rosie-bridge.service").write_text(bridge_unit, encoding="utf-8")
    path = unit_dir / "rosie-watchdog.service"
    path.write_text(watch_unit, encoding="utf-8")
    # bridge binary path is recorded so a later doctor can see it.
    note = config.with_suffix(".bridge-bin")
    note.write_text(bridge + "\n", encoding="utf-8")
    return path


def cmd_watchdog(args: argparse.Namespace) -> int:
    from rosie.watchdog.node import main as watchdog_main

    argv = ["--fleet", args.fleet, "--robot", args.robot, "--profile", args.profile]
    if args.connect:
        argv.extend(["--connect", args.connect])
    if args.secure:
        argv.append("--secure")
    return watchdog_main(argv)


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("robot", help="install the ROS 2 bridge and watchdog on a robot")
    commands = parser.add_subparsers(dest="robot_command")

    setup = commands.add_parser("setup", help="write bridge config, download the bridge, install systemd units")
    setup.add_argument("--fleet", required=True)
    setup.add_argument("--robot", required=True)
    setup.add_argument("--profile", default="rosmaster_x3", choices=PROFILES)
    setup.add_argument("--connect", default="auto", help="router locator, or auto")
    setup.add_argument("--mode", default="client", choices=("client", "peer", "router"))
    setup.add_argument("--config", default=None, help="output config (default: ./rosie-bridge.json5)")
    setup.add_argument("--secure", action="store_true")
    setup.add_argument("--triple", default=None, help="bridge build triple (default: this machine)")
    setup.add_argument("--no-download", action="store_true")
    setup.add_argument("--bridge", default=None, help="bridge binary, with --no-download")
    setup.set_defaults(func=cmd_setup)

    run = commands.add_parser("run", help="resolve connect: auto and exec the bridge")
    run.add_argument("--config", default=None)
    run.add_argument("--bridge", default=None)
    run.add_argument("--triple", default=None)
    run.set_defaults(func=cmd_run)

    doctor = commands.add_parser("doctor", help="check a robot bridge config")
    doctor.add_argument("--config", default=None)
    doctor.set_defaults(func=cmd_doctor)

    watch = commands.add_parser("watchdog", help="run the on-robot safety node")
    watch.add_argument("--fleet", required=True)
    watch.add_argument("--robot", required=True)
    watch.add_argument("--profile", default="default_ros2")
    watch.add_argument("--connect", default=None)
    watch.add_argument("--config", default=None)
    watch.add_argument("--secure", action="store_true")
    watch.set_defaults(func=cmd_watchdog)
