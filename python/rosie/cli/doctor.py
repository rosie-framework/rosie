"""``rosie doctor`` — host install and connectivity checks."""

from __future__ import annotations

import argparse
import glob
import os
import socket

from rosie import __version__
from rosie.cli._common import local_ipv4s


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


def _list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports  # type: ignore

        return [p.device for p in list_ports.comports()]
    except Exception:
        pass
    patterns = ["/dev/cu.usb*", "/dev/ttyACM*", "/dev/ttyUSB*"]
    found: list[str] = []
    for pat in patterns:
        found.extend(sorted(glob.glob(pat)))
    return found


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

    try:
        import zenoh  # noqa: F401

        check("eclipse-zenoh import", True)
    except Exception as e:
        check("eclipse-zenoh import", False, str(e))

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

    from rosie.connect import DEFAULT_CONNECT, is_auto_connect, resolve_connect

    connect = resolve_connect(args.connect)
    if is_auto_connect(connect):
        check("host connect", True, f"{connect} (scout; use --scout to probe)")
        host, port = None, 0
    else:
        host, port = _parse_tcp_locator(connect)
    if host is None and not is_auto_connect(connect):
        check("connect locator parse", False, f"could not parse {connect!r}")
    elif host is not None:
        src = (
            "--connect"
            if args.connect
            else (
                "ROSIE_CONNECT"
                if os.environ.get("ROSIE_CONNECT")
                else f"default {DEFAULT_CONNECT}"
            )
        )
        check("host connect", True, f"{connect} ({src})")
        reachable = _tcp_reachable(host, port, timeout=0.5)
        check(
            "zenohd listen endpoint",
            reachable,
            f"{host}:{port}" + ("" if reachable else " (not accepting connections)"),
        )

    lan = local_ipv4s()
    if lan:
        print(
            "[--] MCU station robots: network.connect: auto (codegen bakes LAN IP) "
            "or "
            + " or ".join(f"tcp/{ip}:7447" for ip in lan[:3])
        )
    if any(ip.startswith("192.168.4.") for ip in lan):
        check("SoftAP-like address (one-robot AP)", True, ", ".join(lan))
    else:
        print(
            f"[--] SoftAP-like address — local IPv4: {', '.join(lan) or 'none'} "
            "(one-robot SoftAP often uses 192.168.4.2; multi-robot fleets use a "
            "dedicated AP — see docs/fleet/networking.md)"
        )

    ports = _list_serial_ports()
    if ports:
        check(
            "serial ports",
            True,
            ", ".join(ports[:6]) + ("…" if len(ports) > 6 else ""),
        )
    else:
        print("[--] serial ports — none detected (ok if no MCU plugged in)")

    try:
        import platformio  # noqa: F401

        check("platformio (rosie-framework[mcu])", True)
    except ImportError:
        print(
            "[--] platformio — not installed "
            '(ok for host-only; use: pip install "rosie-framework[mcu]")'
        )

    print()
    robot = os.environ.get("ROSIE_ROBOT", "robot")
    fleet = os.environ.get("ROSIE_FLEET")
    if fleet:
        identity = f"robot={robot} fleet={fleet}"
    else:
        identity = f"robot={robot} (ROSIE_FLEET unset — required)"
    print(f"[--] default identity — {identity} (ROSIE_ROBOT / ROSIE_FLEET)")
    if not os.environ.get("ROSIE_CONNECT") and not args.connect:
        print(
            f"[--] ROSIE_CONNECT unset — host sessions use {DEFAULT_CONNECT} "
            "(local router). Override for a remote router host."
        )

    if getattr(args, "scout", False):
        print()
        from rosie.discovery import scout_routers

        hellos = scout_routers(timeout_s=1.5)
        if not hellos:
            print(
                "[--] scout — no routers heard on 224.0.0.224:7446 "
                "(multicast blocked, or no zenohd). "
                "Fallback: tcp/<router-host-ip>:7447"
            )
        else:
            check("scout", True, f"{len(hellos)} router(s)")
            for hello in hellos:
                locs = ", ".join(hello.locators) or "—"
                print(f"      zid={hello.zid or '—'} locators={locs}")

    print()
    if ok:
        print("Doctor finished: no hard failures.")
        return 0
    print("Doctor finished: fix FAIL items above (often `rosie setup` + `rosie router`).")
    return 1


def register(sub: argparse._SubParsersAction) -> None:
    p_doc = sub.add_parser("doctor", help="check host install and connectivity")
    p_doc.add_argument(
        "--connect",
        default=None,
        help="override ROSIE_CONNECT for the reachability check",
    )
    p_doc.add_argument(
        "--scout",
        action="store_true",
        help="probe multicast scouting for zenohd on this LAN",
    )
    p_doc.set_defaults(func=cmd_doctor)
