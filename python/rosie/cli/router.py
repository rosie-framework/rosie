"""``rosie router`` — run zenohd."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

from rosie.cli._common import local_ipv4s


def default_config_path() -> Path:
    """Packaged zenoh.json5, with fallback to repo tools/ for editable checkouts."""
    try:
        traj = resources.files("rosie").joinpath("data/zenoh.json5")
        with resources.as_file(traj) as p:
            if p.is_file():
                return Path(p)
    except Exception:
        pass
    # this file: python/rosie/cli/router.py → parents[3] = repo
    repo = Path(__file__).resolve().parents[3]
    candidate = repo / "tools" / "zenoh.json5"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        "Could not find zenoh.json5 package data. Reinstall Rosie or pass --config."
    )


def resolve_router_auth(
    *,
    secure: bool,
    fleet: str | None,
    secret: str | None,
    secret_file: str | None,
    manifest_secret_file: str | Path | None,
) -> str | None:
    """Return plaintext password when the router should enable usrpwd, else None.

    Auth is opt-in via ``--secure`` or an explicit secret override. Presence of a
    leftover secret file alone does not enable auth.
    """
    from rosie.auth import resolve_secret_plaintext

    explicit = bool(
        (secret and str(secret).strip())
        or secret_file
        or (os.environ.get("ROSIE_FLEET_SECRET") or "").strip()
    )
    if not secure and not explicit:
        return None
    return resolve_secret_plaintext(
        secret=secret,
        secret_file=secret_file,
        fleet=fleet,
        secure=secure or explicit,
        manifest_secret_file=manifest_secret_file,
    )


def cmd_router(args: argparse.Namespace) -> int:
    from rosie.auth import bus_mode, write_router_auth_files
    from rosie.bootstrap import find_zenohd
    from rosie.manifest import resolve_manifest

    if getattr(args, "open", False):
        print(
            "note: --open is deprecated and ignored (open bus is the default; "
            "use --secure to enable auth)",
            file=sys.stderr,
        )

    zenohd = find_zenohd(fetch=not args.no_fetch, force=False, quiet=False)

    fleet = args.fleet
    manifest = None
    if args.manifest or fleet:
        try:
            manifest = resolve_manifest(
                manifest=args.manifest,
                fleet=fleet,
                allow_empty_robots=True,
                required=False,
            )
        except Exception:
            manifest = None
    if manifest is not None and not fleet:
        fleet = manifest.fleet

    manifest_secret = None
    if manifest and manifest.secret_file:
        manifest_secret = manifest.secret_file

    secure = bool(args.secure)
    password = resolve_router_auth(
        secure=secure,
        fleet=fleet,
        secret=args.secret,
        secret_file=args.secret_file,
        manifest_secret_file=manifest_secret,
    )

    # If operator asked for --secure but no password resolved, fail clearly.
    if secure and not password and not args.config:
        if fleet:
            print(
                f"error: fleet {fleet!r} has no secret — run "
                f"`rosie fleet init --fleet {fleet} --secure` or "
                f"`rosie fleet secret --fleet {fleet} --set`",
                file=sys.stderr,
            )
        else:
            print(
                "error: could not resolve solo secret for --secure",
                file=sys.stderr,
            )
        return 1

    auth_enabled = bool(password) or (bool(args.config) and secure)
    mode = bus_mode(fleet=fleet, secure=auth_enabled)

    if args.config:
        config = Path(args.config).expanduser()
        if not config.is_file():
            print(f"error: config not found: {config}", file=sys.stderr)
            return 1
        auth_note = "auth: using custom --config (credentials not auto-injected)"
    elif password:
        config, _dict = write_router_auth_files(fleet=fleet, password=password)
        label = fleet or "solo"
        auth_note = f"auth: enabled (usrpwd, user={label})"
    else:
        config = default_config_path()
        auth_note = "auth: disabled (open bus)"

    if not fleet:
        allowlist_note = "allowlist: n/a (solo)"
    elif auth_enabled:
        allowlist_note = "allowlist: host tools only (fleet list/wait need --secure)"
    else:
        allowlist_note = "allowlist: off (open fleet)"

    print(f"Starting zenohd ({zenohd})")
    print(f"  mode: {mode}")
    print(f"  config: {config}")
    print(f"  {auth_note}")
    print(f"  {allowlist_note}")
    if auth_enabled:
        print(
            "  note: --secure requires Zenoh usrpwd "
            "(unsupported on zenoh-pico / ESP32 — use open modes for MCU fleets)",
            file=sys.stderr,
        )
    print("  host tools default to tcp/127.0.0.1:7447 (no ROSIE_CONNECT needed)")
    lan = local_ipv4s()
    if lan:
        print("  put one of these in robot.yaml network.connect (MCU → this laptop):")
        for ip in lan:
            print(f"    tcp/{ip}:7447")
    else:
        print(
            "  (could not detect LAN IP — set robot.yaml network.connect to "
            "tcp/<this-laptop-ip>:7447)"
        )
    cmd = [str(zenohd), "-c", str(config)]
    if args.listen:
        cmd.extend(["--listen", args.listen])
    if args.connect:
        cmd.extend(["--connect", args.connect])
    if args.extra:
        cmd.extend(args.extra)
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


def register(sub: argparse._SubParsersAction) -> None:
    p_router = sub.add_parser("router", help="run the Zenoh router (zenohd)")
    p_router.add_argument(
        "--config",
        default=None,
        help="zenohd JSON5 config (default: packaged listen-all, or auth config when --secure)",
    )
    p_router.add_argument(
        "--secure",
        action="store_true",
        help="enable Zenoh usrpwd (solo: ~/.rosie/solo/secret; fleet: fleet secret)",
    )
    p_router.add_argument(
        "--fleet",
        default=None,
        help="fleet id — topic scope / secret path (open unless --secure)",
    )
    p_router.add_argument(
        "--open",
        action="store_true",
        help=argparse.SUPPRESS,  # deprecated no-op
    )
    p_router.add_argument(
        "--manifest",
        default=None,
        help="fleet manifest (fleet id + optional secret_file)",
    )
    p_router.add_argument("--secret", default=None, help="bus password (one-shot)")
    p_router.add_argument(
        "--secret-file",
        default=None,
        help="path to a file containing the bus password",
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
