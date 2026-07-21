"""Rosie command-line interface."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from importlib import resources
from pathlib import Path

from rosie import __version__


def _default_config_path() -> Path:
    """Packaged zenoh.json5, with fallback to repo tools/ for editable checkouts."""
    try:
        traj = resources.files("rosie").joinpath("data/zenoh.json5")
        with resources.as_file(traj) as p:
            if p.is_file():
                return Path(p)
    except Exception:
        pass
    # Editable / source tree: python/rosie/../.. → repo root is three up from this file? 
    # this file: python/rosie/cli/main.py → parents[2] = python, parents[3] = repo
    repo = Path(__file__).resolve().parents[3]
    candidate = repo / "tools" / "zenoh.json5"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        "Could not find zenoh.json5 package data. Reinstall Rosie or pass --config."
    )


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"rosie {__version__}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from rosie.bootstrap import download_zenohd

    download_zenohd(force=args.force, quiet=False)
    print("Host setup complete (zenohd cached).")
    print("Tip: for MCU projects, run `rosie mcu setup` in the robot directory.")
    return 0


def cmd_router(args: argparse.Namespace) -> int:
    from rosie.bootstrap import find_zenohd

    zenohd = find_zenohd(fetch=not args.no_fetch, force=False, quiet=False)
    config = Path(args.config).expanduser() if args.config else _default_config_path()
    if not config.is_file():
        print(f"error: config not found: {config}", file=sys.stderr)
        return 1

    cmd = [str(zenohd), "-c", str(config)]
    if args.listen:
        cmd.extend(["--listen", args.listen])
    if args.connect:
        cmd.extend(["--connect", args.connect])
    if args.extra:
        cmd.extend(args.extra)

    print(f"Starting zenohd ({zenohd})")
    print(f"  config: {config}")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


def cmd_doctor(args: argparse.Namespace) -> int:
    from rosie.bootstrap import (
        ZENOHD_VERSION,
        find_zenohd,
        zenohd_cache_path,
        zenohd_version_string,
    )

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "ok" if passed else "FAIL"
        if not passed:
            ok = False
        suffix = f" — {detail}" if detail else ""
        print(f"[{mark}] {label}{suffix}")

    print(f"Rosie doctor (rosie {__version__})")
    print()

    # Python client
    try:
        import zenoh  # noqa: F401

        check("eclipse-zenoh import", True)
    except Exception as e:
        check("eclipse-zenoh import", False, str(e))

    # zenohd
    try:
        path = find_zenohd(fetch=False)
        ver = zenohd_version_string(path) or "unknown version"
        check("zenohd binary", True, f"{path} ({ver})")
        if ZENOHD_VERSION not in (ver or ""):
            print(
                f"      note: Rosie prefers zenohd {ZENOHD_VERSION}; "
                "run `rosie setup --force` to refresh the cache."
            )
    except FileNotFoundError:
        check(
            "zenohd binary",
            False,
            f"not on PATH or at {zenohd_cache_path()}; run `rosie setup`",
        )

    # Connect endpoint
    connect = args.connect or os.environ.get("ROSIE_CONNECT", "tcp/127.0.0.1:7447")
    host, port = _parse_tcp_locator(connect)
    if host is None:
        check("ROSIE_CONNECT parse", False, f"could not parse {connect!r}")
    else:
        check("ROSIE_CONNECT", True, connect)
        reachable = _tcp_reachable(host, port, timeout=0.5)
        check(
            "zenohd listen endpoint",
            reachable,
            f"{host}:{port}" + ("" if reachable else " (not accepting connections)"),
        )

    # SoftAP solo-fallback / common IP hint
    softap_ips = _local_ipv4s()
    if any(ip.startswith("192.168.4.") for ip in softap_ips):
        check("SoftAP-like address (solo fallback)", True, ", ".join(softap_ips))
    else:
        print(
            f"[--] SoftAP-like address — local IPv4: "
            f"{', '.join(softap_ips) or 'none'} "
            "(solo SoftAP often uses 192.168.4.2; fleets use a dedicated AP — "
            "see docs/fleet-networking.md)"
        )

    # Serial ports (best-effort)
    ports = _list_serial_ports()
    if ports:
        check("serial ports", True, ", ".join(ports[:6]) + ("…" if len(ports) > 6 else ""))
    else:
        print("[--] serial ports — none detected (ok if no MCU plugged in)")

    # PlatformIO
    try:
        import platformio  # noqa: F401

        check("platformio (rosie[mcu])", True)
    except ImportError:
        print(
            "[--] platformio — not installed "
            '(ok for host-only; use: pip install "rosie[mcu]")'
        )

    print()
    robot = os.environ.get("ROSIE_ROBOT", "robot")
    fleet = os.environ.get("ROSIE_FLEET")
    identity = f"robot={robot}" + (f" fleet={fleet}" if fleet else " (no fleet)")
    print(f"[--] default identity — {identity} (ROSIE_ROBOT / ROSIE_FLEET)")
    if not os.environ.get("ROSIE_CONNECT") and not args.connect:
        print(
            "[--] ROSIE_CONNECT unset — host sessions may peer-scout; "
            "set ROSIE_CONNECT=tcp/<router-host>:7447 for fleets "
            "(docs/fleet-networking.md)"
        )

    print()
    if ok:
        print("Doctor finished: no hard failures.")
        return 0
    print("Doctor finished: fix FAIL items above (often `rosie setup` + `rosie router`).")
    return 1


def _parse_tcp_locator(locator: str) -> tuple[str | None, int]:
    # Forms: tcp/127.0.0.1:7447 or tcp/0.0.0.0:7447
    s = locator.strip()
    if s.startswith("tcp/"):
        s = s[4:]
    if ":" not in s:
        return None, 0
    host, _, port_s = s.rpartition(":")
    try:
        return host or None, int(port_s)
    except ValueError:
        return None, 0


def _tcp_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _local_ipv4s() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    # Also try connecting outbound to discover primary IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips


def _list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports  # type: ignore

        return [p.device for p in list_ports.comports()]
    except Exception:
        pass
    # Fallback: common device nodes
    import glob

    patterns = ["/dev/cu.usb*", "/dev/ttyACM*", "/dev/ttyUSB*"]
    found: list[str] = []
    for pat in patterns:
        found.extend(sorted(glob.glob(pat)))
    return found


def cmd_teleop(args: argparse.Namespace) -> int:
    from rosie.tools.teleop_twist import run_teleop

    run_teleop(
        robot=args.robot,
        fleet=args.fleet,
        v_fwd=args.v_fwd,
        v_turn=args.v_turn,
        pub_hz=args.hz,
    )
    return 0


def _resolve_fleet_id(args: argparse.Namespace) -> str:
    fleet = getattr(args, "fleet", None) or os.environ.get("ROSIE_FLEET")
    if not fleet:
        raise SystemExit("error: --fleet or ROSIE_FLEET is required")
    return fleet


def cmd_fleet_list(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = _resolve_fleet_id(args)
    with Fleet(fleet_id, connect=args.connect) as fleet:
        robots = fleet.robots(ttl_s=args.ttl, wait_s=args.wait)
        if not robots:
            print(f"No robots seen in fleet {fleet_id!r} (ttl={args.ttl}s).")
            return 0
        print(f"Fleet {fleet_id}: {len(robots)} robot(s)")
        for r in robots:
            fid = r.fleet_id or fleet_id
            print(f"  {r.robot_id:16} status={r.status:8} fleet={fid}")
    return 0


def cmd_fleet_estop(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = _resolve_fleet_id(args)
    with Fleet(fleet_id, connect=args.connect) as fleet:
        fleet.publish_estop()
        print(f"Published estop on {fleet_id}/_fleet/estop")
    return 0


def cmd_fleet_leader(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = _resolve_fleet_id(args)
    with Fleet(fleet_id, connect=args.connect) as fleet:
        if args.claim:
            claim = fleet.claim_leader(args.claim, term=args.term)
            print(f"Claimed leader: robot={claim.robot_id} term={claim.term}")
            return 0
        leader = fleet.get_leader(wait_s=args.wait)
        if leader is None:
            print(f"No leader claim heard on {fleet_id}/_fleet/coord/leader")
            return 0
        print(f"Leader: robot={leader.robot_id} term={leader.term}")
    return 0


def cmd_fleet_wait(args: argparse.Namespace) -> int:
    from rosie import Fleet, load_manifest

    manifest = None
    connect = args.connect
    if args.manifest:
        manifest = load_manifest(args.manifest)
        fleet_id = manifest.fleet
        connect = connect or manifest.connect
        expect = manifest
    else:
        fleet_id = _resolve_fleet_id(args)
        if not args.expect:
            print(
                "error: provide --manifest or --expect id1,id2",
                file=sys.stderr,
            )
            return 2
        expect = [x.strip() for x in args.expect.split(",") if x.strip()]

    try:
        with Fleet(fleet_id, connect=connect) as fleet:
            ready = fleet.wait(
                expect,
                timeout_s=args.timeout,
                ttl_s=args.ttl,
                status=args.status,
                poll_s=args.poll,
            )
    except TimeoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Fleet {fleet_id}: ready ({len(ready)} robot(s))")
    for r in ready:
        print(f"  {r.robot_id:16} status={r.status}")
    return 0


def cmd_fleet_topics(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = _resolve_fleet_id(args)
    with Fleet(fleet_id, connect=args.connect) as fleet:
        topic_map = fleet.topics(selector=args.key, wait_s=args.wait)
    if not topic_map.by_robot:
        print(
            f"No topics heard under fleet {fleet_id!r} "
            f"(listened {args.wait}s; publishers must be active)."
        )
        return 0
    if args.flat:
        for key in topic_map.flat():
            print(key)
        return 0
    print(f"Fleet {fleet_id}:")
    for robot, rels in topic_map.by_robot.items():
        print(f"  {robot}/")
        for rel in rels:
            label = rel if rel else "(root)"
            print(f"    {label}")
    return 0


def cmd_topic_list(args: argparse.Namespace) -> int:
    return cmd_fleet_topics(args)


def cmd_topic_echo(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet_id = _resolve_fleet_id(args)
    bag.echo_stream(
        fleet=fleet_id,
        key=args.key,
        connect=args.connect,
        max_count=args.count,
        raw=args.raw,
    )
    return 0


def cmd_bag_record(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet_id = _resolve_fleet_id(args)

    def _progress(key: str, _raw: bytes) -> None:
        if args.verbose:
            print(key, file=sys.stderr)

    bag.record(
        fleet=fleet_id,
        output=args.output,
        selector=args.key,
        connect=args.connect,
        on_sample=_progress if args.verbose else None,
    )
    return 0


def cmd_bag_play(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet = args.fleet or os.environ.get("ROSIE_FLEET")
    try:
        bag.play(args.bag, connect=args.connect, rate=args.rate, fleet=fleet)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_drivers_list(args: argparse.Namespace) -> int:
    from rosie.robot_config import format_drivers_list, load_registry

    print(format_drivers_list(load_registry(), category=args.category), end="")
    return 0


def _parse_waypoints(cmd: str) -> list[tuple[float, float]] | None:
    parts = cmd.split()
    if len(parts) < 2 or len(parts) % 2 != 0:
        return None
    waypoints: list[tuple[float, float]] = []
    for i in range(0, len(parts), 2):
        try:
            waypoints.append((float(parts[i]), float(parts[i + 1])))
        except ValueError:
            return None
    return waypoints


def cmd_drive(args: argparse.Namespace) -> int:
    """Interactive waypoint / teleop REPL for a MobileBase robot."""
    from pathlib import Path

    from rosie.robot import Robot
    from rosie.robot_config import find_robot_yaml

    config = args.config
    if not config:
        found = find_robot_yaml(Path(args.dir))
        config = str(found) if found else None

    print("Opening Rosie session (zenohd / `rosie router` must be running)...")
    try:
        bot = Robot(
            robot=args.robot,
            fleet=args.fleet,
            connect=args.connect,
            name="drive",
            config_path=config,
        )
    except Exception as e:
        print(f"Could not open session: {e}", file=sys.stderr)
        return 1

    print(f"Robot id: {bot.robot_id}")
    p = bot.wait_for_pose(3.0)
    if p:
        print(
            f"Linked. pose x={p.get('x', 0):.3f} y={p.get('y', 0):.3f} "
            f"mode={p.get('mode', '?')}"
        )
        try:
            bot.zero()
            print("Pose zero requested.")
        except Exception as e:
            print(f"  warning: zero failed: {e}")
    else:
        print("No pose yet — CLI is up, but the robot is not publishing.")

    print("Commands: x y [x y ...] | teleop | snap | cam | zero | imu | stop | quit")
    while True:
        try:
            cmd = input("target> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        low = cmd.lower()
        if low in ("quit", "exit", "q"):
            break
        if low == "stop":
            bot.stop()
            print("  STOP sent.")
            continue
        if low == "zero":
            bot.zero()
            print("  pose zeroed.")
            continue
        if low == "imu":
            bot.set_heading_source(None)
            print("  heading_source toggle sent.")
            continue
        if low == "snap":
            try:
                bot.snap()
            except Exception as e:
                print(f"  snap failed: {e}")
            continue
        if low == "cam":
            try:
                bot.camera_live()
            except Exception as e:
                print(f"  cam failed: {e}")
            continue
        if low == "teleop":
            try:
                bot.teleop()
            except Exception as e:
                print(f"  teleop failed: {e}")
            continue
        waypoints = _parse_waypoints(cmd)
        if waypoints is None:
            print("  enter pairs 'x y [x y ...]', or teleop / snap / cam / stop / quit")
            continue
        try:
            bot.drive_route(waypoints)
        except KeyboardInterrupt:
            pass

    bot.close()
    print("Bye.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosie",
        description="Rosie — batteries-included robotics CLI over Zenoh",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    p_ver = sub.add_parser("version", help="print Rosie version")
    p_ver.set_defaults(func=cmd_version)

    p_setup = sub.add_parser(
        "setup",
        help="download/cache zenohd while online (before joining an offline demo AP)",
    )
    p_setup.add_argument(
        "--force", action="store_true", help="re-download even if cached"
    )
    p_setup.set_defaults(func=cmd_setup)

    p_router = sub.add_parser("router", help="run the Zenoh router (zenohd)")
    p_router.add_argument(
        "--config",
        default=None,
        help="zenohd JSON5 config (default: packaged listen-all config)",
    )
    p_router.add_argument(
        "--listen",
        default=None,
        help="extra --listen endpoint passed to zenohd",
    )
    p_router.add_argument(
        "--connect",
        default=None,
        help="extra --connect endpoint passed to zenohd",
    )
    p_router.add_argument(
        "--no-fetch",
        action="store_true",
        help="do not download zenohd if missing",
    )
    p_router.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="extra args after -- passed to zenohd",
    )
    p_router.set_defaults(func=cmd_router)

    p_doc = sub.add_parser("doctor", help="check host install and connectivity")
    p_doc.add_argument(
        "--connect",
        default=None,
        help="override ROSIE_CONNECT for the reachability check",
    )
    p_doc.set_defaults(func=cmd_doctor)

    p_tele = sub.add_parser("teleop", help="WASD keyboard teleop → <robot>/cmd_vel")
    p_tele.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT", "robot"),
        help="robot id (default: ROSIE_ROBOT or robot)",
    )
    p_tele.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="optional fleet id (default: ROSIE_FLEET)",
    )
    p_tele.add_argument("--v-fwd", type=float, default=0.25, help="forward speed m/s")
    p_tele.add_argument("--v-turn", type=float, default=1.0, help="yaw rate rad/s")
    p_tele.add_argument("--hz", type=float, default=10.0, help="publish rate")
    p_tele.set_defaults(func=cmd_teleop)

    p_drive = sub.add_parser(
        "drive",
        help="interactive waypoint / teleop / camera REPL for a MobileBase robot",
    )
    p_drive.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT"),
        help="robot id (default: robot.yaml / ROSIE_ROBOT)",
    )
    p_drive.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="optional fleet id",
    )
    p_drive.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p_drive.add_argument(
        "--config",
        default=None,
        help="path to robot.yaml (default: ./robot.yaml if present)",
    )
    p_drive.add_argument(
        "--dir",
        default=".",
        help="directory to search for robot.yaml (default: cwd)",
    )
    p_drive.set_defaults(func=cmd_drive)

    from rosie.tools.tune import cmd_tune

    p_tune = sub.add_parser(
        "tune",
        help="live-tune onboard velocity PID gains (interactive / set / save)",
    )
    tune_sub = p_tune.add_subparsers(dest="tune_command")

    def _tune_common(p: argparse.ArgumentParser, *, config_required: bool = False) -> None:
        p.add_argument("--robot", default=None, help="robot id (or from --config)")
        p.add_argument("--fleet", default=None, help="optional fleet id")
        p.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
        p.add_argument(
            "--config",
            default=None,
            required=config_required,
            help="robot.yaml (defaults + save target)",
        )
        p.add_argument(
            "--dir",
            default=".",
            help="project dir to search for robot.yaml when --config omitted",
        )
        p.add_argument("--kp", type=float, default=None)
        p.add_argument("--ki", type=float, default=None)
        p.add_argument("--kd", type=float, default=None)
        p.add_argument("--i-clamp", dest="i_clamp", type=float, default=None)
        p.set_defaults(func=cmd_tune)

    _tune_common(p_tune)
    p_tset = tune_sub.add_parser("set", help="one-shot set_gains to the robot")
    _tune_common(p_tset)
    p_tsave = tune_sub.add_parser(
        "save",
        help="write control.velocity into robot.yaml (from flags or live robot)",
    )
    _tune_common(p_tsave, config_required=True)

    p_drivers = sub.add_parser("drivers", help="list Rosie driver / base inventory")
    drivers_sub = p_drivers.add_subparsers(dest="drivers_command")
    p_dlist = drivers_sub.add_parser("list", help="print supported and planned drivers")
    p_dlist.add_argument(
        "--category",
        default=None,
        help="filter: motors, encoders, imu, camera, base, network",
    )
    p_dlist.set_defaults(func=cmd_drivers_list)

    p_fleet = sub.add_parser("fleet", help="fleet discovery, bring-up, and coordination")
    fleet_sub = p_fleet.add_subparsers(dest="fleet_command")

    def _fleet_common(p: argparse.ArgumentParser, *, fleet_required: bool = False) -> None:
        p.add_argument(
            "--fleet",
            default=os.environ.get("ROSIE_FLEET"),
            required=fleet_required,
            help="fleet id (default: ROSIE_FLEET)",
        )
        p.add_argument(
            "--connect",
            default=None,
            help="override ROSIE_CONNECT",
        )

    p_flist = fleet_sub.add_parser("list", help="list robots from presence heartbeats")
    _fleet_common(p_flist)
    p_flist.add_argument("--ttl", type=float, default=3.0, help="presence TTL seconds")
    p_flist.add_argument("--wait", type=float, default=0.5, help="listen window seconds")
    p_flist.set_defaults(func=cmd_fleet_list)

    p_fwait = fleet_sub.add_parser(
        "wait",
        help="wait until expected robots are present (team bring-up)",
    )
    _fleet_common(p_fwait)
    p_fwait.add_argument(
        "--manifest",
        default=None,
        help="fleet manifest JSON/YAML (sets fleet + expected robots)",
    )
    p_fwait.add_argument(
        "--expect",
        default=None,
        help="comma-separated robot ids (alternative to --manifest)",
    )
    p_fwait.add_argument(
        "--status",
        default=None,
        help="required presence status for all expected robots",
    )
    p_fwait.add_argument("--timeout", type=float, default=30.0, help="seconds to wait")
    p_fwait.add_argument("--ttl", type=float, default=3.0, help="presence TTL seconds")
    p_fwait.add_argument("--poll", type=float, default=0.5, help="poll interval seconds")
    p_fwait.set_defaults(func=cmd_fleet_wait)

    p_ftopics = fleet_sub.add_parser(
        "topics",
        help="list topics heard under the fleet (grouped by robot)",
    )
    _fleet_common(p_ftopics)
    p_ftopics.add_argument(
        "--key",
        default="**",
        help="selector relative to fleet (default: **)",
    )
    p_ftopics.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="listen window seconds (publishers must be active)",
    )
    p_ftopics.add_argument(
        "--flat",
        action="store_true",
        help="print full keyexprs one per line",
    )
    p_ftopics.set_defaults(func=cmd_fleet_topics)

    p_festop = fleet_sub.add_parser("estop", help="publish fleet emergency stop")
    _fleet_common(p_festop)
    p_festop.set_defaults(func=cmd_fleet_estop)

    p_flead = fleet_sub.add_parser("leader", help="get or claim fleet leader")
    _fleet_common(p_flead)
    p_flead.add_argument("--claim", default=None, help="robot id to claim as leader")
    p_flead.add_argument("--term", type=int, default=1, help="claim term (with --claim)")
    p_flead.add_argument("--wait", type=float, default=0.5, help="listen window when getting")
    p_flead.set_defaults(func=cmd_fleet_leader)

    p_topic = sub.add_parser("topic", help="fleet-scoped topic introspection")
    topic_sub = p_topic.add_subparsers(dest="topic_command")

    p_tlist = topic_sub.add_parser("list", help="list topics under a fleet (by robot)")
    _fleet_common(p_tlist)
    p_tlist.add_argument("--key", default="**", help="selector relative to fleet")
    p_tlist.add_argument("--wait", type=float, default=2.0, help="listen window seconds")
    p_tlist.add_argument("--flat", action="store_true", help="print full keyexprs")
    p_tlist.set_defaults(func=cmd_topic_list)

    p_techo = topic_sub.add_parser("echo", help="print live samples for a fleet key")
    _fleet_common(p_techo)
    p_techo.add_argument(
        "--key",
        required=True,
        help="key relative to fleet (e.g. */pose, car1/cmd_vel, _fleet/estop)",
    )
    p_techo.add_argument("--count", type=int, default=None, help="stop after N samples")
    p_techo.add_argument("--raw", action="store_true", help="print repr of bytes")
    p_techo.set_defaults(func=cmd_topic_echo)

    p_bag = sub.add_parser("bag", help="record/play fleet traffic from the router host")
    bag_sub = p_bag.add_subparsers(dest="bag_command")

    p_brec = bag_sub.add_parser("record", help="record fleet topics to a .rosiebag file")
    _fleet_common(p_brec)
    p_brec.add_argument(
        "-o",
        "--output",
        required=True,
        help="output path (JSONL .rosiebag)",
    )
    p_brec.add_argument(
        "--key",
        default="**",
        help="selector relative to fleet (default: **)",
    )
    p_brec.add_argument("-v", "--verbose", action="store_true", help="print keys as recorded")
    p_brec.set_defaults(func=cmd_bag_record)

    p_bplay = bag_sub.add_parser("play", help="replay a .rosiebag onto the bus")
    p_bplay.add_argument("bag", help="path to .rosiebag")
    p_bplay.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="override fleet id (default: bag header / ROSIE_FLEET)",
    )
    p_bplay.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p_bplay.add_argument("--rate", type=float, default=1.0, help="playback rate multiplier")
    p_bplay.set_defaults(func=cmd_bag_play)

    # MCU subcommands (PlatformIO) — not for Pi / Jetson / laptop hosts
    from rosie.cli import mcu

    mcu.register(sub)

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Allow `rosie --version`
    if argv == ["--version"] or argv == ["-V"]:
        print(f"rosie {__version__}")
        raise SystemExit(0)

    parser = build_parser()
    # Strip a leading `--` from remainder for router passthrough
    args = parser.parse_args(argv)
    if getattr(args, "extra", None):
        extra = list(args.extra)
        if extra and extra[0] == "--":
            extra = extra[1:]
        args.extra = extra

    if getattr(args, "version", False) and not getattr(args, "command", None):
        print(f"rosie {__version__}")
        raise SystemExit(0)

    if not getattr(args, "command", None):
        parser.print_help()
        raise SystemExit(0)

    if args.command == "fleet" and not getattr(args, "fleet_command", None):
        print(
            "usage: rosie fleet {list,wait,topics,estop,leader} ...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if args.command == "topic" and not getattr(args, "topic_command", None):
        print("usage: rosie topic {list,echo} ...", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "bag" and not getattr(args, "bag_command", None):
        print("usage: rosie bag {record,play} ...", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "mcu" and not getattr(args, "mcu_command", None):
        print(
            "usage: rosie mcu {setup,link,init,gen-config,build,flash,monitor} ...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if args.command == "drivers" and not getattr(args, "drivers_command", None):
        print("usage: rosie drivers list [--category ...]", file=sys.stderr)
        raise SystemExit(2)

    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
