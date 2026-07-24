"""``rosie fleet`` — discovery, bring-up, enrollment, and coordination."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Any

from rosie.cli._common import add_fleet_common, resolve_fleet_id


def _fleet_kwargs(args: argparse.Namespace) -> dict:
    """Build Fleet() kwargs; allowlist + usrpwd only when ``--secure``."""
    from rosie.manifest import resolve_manifest

    secure = bool(getattr(args, "secure", False))
    manifest = resolve_manifest(
        manifest=getattr(args, "manifest", None),
        fleet=getattr(args, "fleet", None) or None,
        allow_empty_robots=True,
        required=False,
    )
    allowlist = None
    fleet_id = None
    connect = getattr(args, "connect", None)
    if manifest is not None:
        fleet_id = manifest.fleet
        connect = connect or manifest.connect
        # Allowlist is a host-tool concern and only applies in fleet-secure mode.
        if secure and not getattr(args, "all", False):
            allowlist = manifest.allowed_ids()
    if fleet_id is None:
        fleet_id = resolve_fleet_id(args)
    return {
        "fleet": fleet_id,
        "connect": connect,
        "allowlist": allowlist,
        "secure": secure,
        "manifest": manifest,
    }


def _open_fleet(kw: dict) -> Any:
    from rosie import Fleet

    return Fleet(
        kw["fleet"],
        connect=kw["connect"],
        allowlist=kw.get("allowlist"),
        secure=bool(kw.get("secure")),
    )


def cmd_fleet_list(args: argparse.Namespace) -> int:
    kw = _fleet_kwargs(args)
    manifest = kw.pop("manifest")
    secure = bool(kw.get("secure"))
    with _open_fleet(kw) as fleet:
        robots = fleet.robots(
            ttl_s=args.ttl,
            wait_s=args.wait,
            include_all=args.all or not secure,
        )
        ignored = []
        if secure and manifest is not None and not args.all:
            ignored = fleet.ignored_robots(ttl_s=args.ttl, wait_s=0.0)
        if not robots:
            print(f"No robots seen in fleet {kw['fleet']!r} (ttl={args.ttl}s).")
            if secure and manifest is None:
                print(
                    "(tip: pass --fleet after `rosie fleet init`, or --manifest, "
                    "to filter by allowlist)",
                    file=sys.stderr,
                )
            elif secure and manifest is not None and not manifest.robots:
                print(
                    f"(manifest {manifest.path} has no enrolled robots — "
                    f"`rosie fleet add --fleet {kw['fleet']} --robot <id>`)",
                    file=sys.stderr,
                )
            return 0
        mode = "fleet-secure" if secure else "fleet-open"
        print(f"Fleet {kw['fleet']} [{mode}]: {len(robots)} robot(s)")
        for r in robots:
            fid = r.fleet_id or kw["fleet"]
            print(f"  {r.robot_id:16} status={r.status:8} fleet={fid}")
        if ignored:
            print(f"Ignored (not enrolled): {', '.join(m.robot_id for m in ignored)}")
    return 0


def cmd_fleet_estop(args: argparse.Namespace) -> int:
    kw = _fleet_kwargs(args)
    kw.pop("manifest", None)
    with _open_fleet(kw) as fleet:
        fleet.publish_estop()
        print(f"Published estop on {kw['fleet']}/_fleet/estop")
    return 0


def cmd_fleet_leader(args: argparse.Namespace) -> int:
    kw = _fleet_kwargs(args)
    kw.pop("manifest", None)
    with _open_fleet(kw) as fleet:
        if args.claim:
            claim = fleet.claim_leader(args.claim, term=args.term)
            print(f"Claimed leader: robot={claim.robot_id} term={claim.term}")
            return 0
        leader = fleet.get_leader(wait_s=args.wait)
        if leader is None:
            print(f"No leader claim heard on {kw['fleet']}/_fleet/coord/leader")
            return 0
        print(f"Leader: robot={leader.robot_id} term={leader.term}")
    return 0


def cmd_fleet_wait(args: argparse.Namespace) -> int:
    import time

    from rosie.manifest import load_manifest, resolve_manifest

    secure = bool(getattr(args, "secure", False))
    connect = args.connect
    expect: object | None = None
    fleet_id: str

    expect_ids = (
        [x.strip() for x in args.expect.split(",") if x.strip()]
        if args.expect
        else None
    )

    if args.manifest:
        manifest = load_manifest(args.manifest, allow_empty_robots=True)
        fleet_id = manifest.fleet
        connect = connect or manifest.connect
        if expect_ids is not None:
            expect = expect_ids
        elif secure:
            if not manifest.robots:
                print(
                    f"error: manifest has no robots — "
                    f"`rosie fleet add --fleet {manifest.fleet} --robot <id>`",
                    file=sys.stderr,
                )
                return 2
            expect = manifest
        else:
            expect = None
    elif expect_ids is not None:
        fleet_id = resolve_fleet_id(args)
        expect = expect_ids
    else:
        manifest = resolve_manifest(
            fleet=args.fleet,
            allow_empty_robots=True,
            required=False,
        )
        if manifest is None:
            print(
                "error: provide --manifest, --expect id1,id2, or --fleet after fleet init",
                file=sys.stderr,
            )
            return 2
        fleet_id = manifest.fleet
        connect = connect or manifest.connect
        if secure:
            if not manifest.robots:
                print(
                    f"error: manifest has no robots — "
                    f"`rosie fleet add --fleet {manifest.fleet} --robot <id>`",
                    file=sys.stderr,
                )
                return 2
            expect = manifest
        else:
            expect = None

    try:
        with _open_fleet(
            {
                "fleet": fleet_id,
                "connect": connect,
                "allowlist": None,
                "secure": secure,
            }
        ) as fleet:
            if expect is None:
                deadline = time.monotonic() + args.timeout
                ready = []
                while time.monotonic() < deadline:
                    ready = fleet.robots(
                        ttl_s=args.ttl, wait_s=args.poll, include_all=True
                    )
                    if ready:
                        break
                    time.sleep(args.poll)
                if not ready:
                    raise TimeoutError(
                        f"no robots seen in fleet {fleet_id!r} within {args.timeout}s"
                    )
            else:
                ready = fleet.wait(
                    expect,  # type: ignore[arg-type]
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
    kw = _fleet_kwargs(args)
    kw.pop("manifest", None)
    secure = bool(kw.get("secure"))
    with _open_fleet(kw) as fleet:
        topic_map = fleet.topics(
            selector=args.key,
            wait_s=args.wait,
            include_all=args.all or not secure,
        )
    if not topic_map.by_robot:
        print(
            f"No topics heard under fleet {kw['fleet']!r} "
            f"(listened {args.wait}s; publishers must be active)."
        )
        return 0
    if args.flat:
        for key in topic_map.flat():
            print(key)
        return 0
    print(f"Fleet {kw['fleet']}:")
    for robot, rels in topic_map.by_robot.items():
        print(f"  {robot}/")
        for rel in rels:
            label = rel if rel else "(root)"
            print(f"    {label}")
    return 0


def _short_home(p: Path) -> str:
    home = str(Path.home())
    s = str(p)
    return s.replace(home, "~", 1) if s.startswith(home) else s


def _print_init_banner(
    fleet_id: str,
    manifest_path: Path,
    *,
    secret_path: Path | None = None,
    secret: str | None = None,
) -> None:
    print(f"Created fleet {fleet_id!r}")
    print(f"  manifest: {_short_home(manifest_path)}")
    if secret_path is not None and secret is not None:
        print(f"  secret:   {_short_home(secret_path)}")
        print()
        print("Fleet secret (share out-of-band with robot builders; not sent over the bus):")
        print(f"  {secret}")
        print()
        print("Next steps:")
        print(f"  1. Enroll robots:  rosie fleet add --fleet {fleet_id} --robot <id>")
        print(
            f"                     (or: rosie fleet add --fleet {fleet_id} --from robot.yaml)"
        )
        print("  2. Share the fleet secret with anyone who will build/flash a robot")
        print(f"     (they run: rosie fleet secret --fleet {fleet_id} --set)")
        print("  3. On each robot: set fleet: <id>, then `rosie secret apply`")
        print(f"  4. Start secure bus:  rosie router --fleet {fleet_id} --secure")
        print(f"  5. Wait for the team: rosie fleet wait --fleet {fleet_id} --secure")
    else:
        print("  mode:    fleet-open (no bus secret)")
        print()
        print("Next steps:")
        print(f"  1. Enroll robots:  rosie fleet add --fleet {fleet_id} --robot <id>")
        print(f"  2. Start open bus: rosie router --fleet {fleet_id}")
        print(f"  3. List / wait:    rosie fleet list --fleet {fleet_id}")
        print(
            f"  (later) Secure:   rosie fleet init --fleet {fleet_id} --secure --force, "
            "or `rosie fleet secret --set`"
        )


def cmd_fleet_init(args: argparse.Namespace) -> int:
    from rosie.fleet_home import (
        default_manifest_path,
        default_secret_path,
        ensure_dir,
        fleet_dir,
        generate_secret,
        write_secret_file,
    )
    from rosie.manifest import FleetManifest, save_manifest

    fleet_id = resolve_fleet_id(args)
    out = Path(args.output).expanduser().resolve() if args.output else default_manifest_path(fleet_id)
    secret_path = default_secret_path(fleet_id)
    secure = bool(getattr(args, "secure", False))
    if out.exists() and not args.force:
        print(f"error: manifest already exists: {out} (pass --force)", file=sys.stderr)
        return 1
    if secure and secret_path.exists() and not args.force:
        print(f"error: secret already exists: {secret_path} (pass --force)", file=sys.stderr)
        return 1

    ensure_dir(fleet_dir(fleet_id))
    manifest = FleetManifest(fleet=fleet_id, robots=(), path=out)
    save_manifest(manifest, out)
    if secure:
        secret = generate_secret()
        write_secret_file(secret_path, secret)
        _print_init_banner(fleet_id, out, secret_path=secret_path, secret=secret)
    else:
        _print_init_banner(fleet_id, out)
    return 0


def _robot_from_config(path: Path) -> tuple[str, str | None]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping")
    rid = data.get("robot") or data.get("robot_id") or data.get("id")
    if not rid:
        raise ValueError(f"{path}: missing 'robot' field")
    kind = data.get("kind") or data.get("type")
    base = data.get("base") or {}
    if not kind and isinstance(base, dict) and base.get("type"):
        kind = str(base.get("type"))
    return str(rid).strip(), str(kind) if kind else None


def cmd_fleet_add(args: argparse.Namespace) -> int:
    from rosie.manifest import (
        RobotSpec,
        add_robot,
        resolve_manifest,
        save_manifest,
    )

    fleet_id = args.fleet
    try:
        manifest = resolve_manifest(
            manifest=args.manifest,
            fleet=fleet_id,
            allow_empty_robots=True,
            required=True,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    assert manifest is not None

    kind = args.kind
    if args.from_config:
        raw = args.from_config
        path = Path(raw).expanduser()
        if not path.is_file():
            path = (Path.cwd() / raw).resolve()
        if not path.is_file():
            print(f"error: config not found: {args.from_config}", file=sys.stderr)
            return 2
        path = path.resolve()
        try:
            rid, kind_from = _robot_from_config(path)
            if kind is None:
                kind = kind_from
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    elif args.robot:
        rid = args.robot
    else:
        print("error: provide --robot <id> or --from robot.yaml", file=sys.stderr)
        return 2

    try:
        updated = add_robot(manifest, RobotSpec(id=rid, kind=kind, status=args.status))
        path = save_manifest(updated, args.manifest or manifest.path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Enrolled {rid!r} in fleet {updated.fleet!r} ({path})")
    return 0


def cmd_fleet_remove(args: argparse.Namespace) -> int:
    from rosie.manifest import remove_robot, resolve_manifest, save_manifest

    try:
        manifest = resolve_manifest(
            manifest=args.manifest,
            fleet=args.fleet,
            allow_empty_robots=True,
            required=True,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    assert manifest is not None
    try:
        updated = remove_robot(manifest, args.robot)
        path = save_manifest(updated, args.manifest or manifest.path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Removed {args.robot!r} from fleet {updated.fleet!r} ({path})")
    return 0


def cmd_fleet_secret(args: argparse.Namespace) -> int:
    from rosie.fleet_home import (
        default_secret_path,
        generate_secret,
        read_secret_file,
        write_secret_file,
    )
    from rosie.manifest import resolve_manifest

    fleet_id = resolve_fleet_id(args)
    manifest = resolve_manifest(
        manifest=args.manifest,
        fleet=fleet_id,
        allow_empty_robots=True,
        required=False,
    )
    if manifest and manifest.secret_file:
        secret_path = Path(manifest.secret_file).expanduser()
    else:
        secret_path = default_secret_path(fleet_id)

    if args.set:
        value = args.set if args.set is not True and args.set != "" else None
        if value is None:
            value = getpass.getpass("Fleet secret: ").strip()
        if not value:
            print("error: empty secret", file=sys.stderr)
            return 2
        write_secret_file(secret_path, value)
        print(f"Wrote secret to {secret_path}")
        return 0

    if args.rotate:
        secret = generate_secret()
        write_secret_file(secret_path, secret)
        print(f"Rotated secret for fleet {fleet_id!r}")
        print(f"  secret file: {secret_path}")
        print()
        print("New fleet secret (re-share out-of-band; rebuild/flash every robot):")
        print(f"  {secret}")
        return 0

    # --show (default when no set/rotate)
    secret = read_secret_file(secret_path)
    if not secret:
        print(f"error: no secret at {secret_path} (run fleet init or --set)", file=sys.stderr)
        return 1
    print(secret)
    return 0


def _add_secure_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--secure",
        action="store_true",
        help="fleet-secure: Zenoh usrpwd + manifest allowlist (default: open)",
    )


def _add_manifest_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--manifest",
        default=None,
        help="manifest path (default: ~/.rosie/fleets/<fleet>/manifest.yaml or ROSIE_FLEET_MANIFEST)",
    )


def register(sub: argparse._SubParsersAction) -> None:
    p_fleet = sub.add_parser("fleet", help="fleet discovery, bring-up, and coordination")
    fleet_sub = p_fleet.add_subparsers(dest="fleet_command")

    p_init = fleet_sub.add_parser(
        "init",
        help="create fleet home under ~/.rosie (manifest; optional secret with --secure)",
    )
    add_fleet_common(p_init, fleet_required=True)
    p_init.add_argument("-o", "--output", default=None, help="manifest path override")
    p_init.add_argument(
        "--secure",
        action="store_true",
        help="also create fleet bus secret (for fleet-secure mode)",
    )
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.set_defaults(func=cmd_fleet_init)

    p_add = fleet_sub.add_parser("add", help="enroll a robot id into the fleet allowlist")
    add_fleet_common(p_add)
    _add_manifest_arg(p_add)
    p_add.add_argument("--robot", default=None, help="robot id to enroll")
    p_add.add_argument(
        "--from",
        dest="from_config",
        default=None,
        help="robot.yaml / agent.yaml to read robot id (and kind) from",
    )
    p_add.add_argument("--kind", default=None, help="optional device kind")
    p_add.add_argument("--status", default=None, help="optional required presence status")
    p_add.set_defaults(func=cmd_fleet_add)

    p_rm = fleet_sub.add_parser("remove", help="remove a robot id from the allowlist")
    add_fleet_common(p_rm)
    _add_manifest_arg(p_rm)
    p_rm.add_argument("--robot", required=True, help="robot id to remove")
    p_rm.set_defaults(func=cmd_fleet_remove)

    p_sec = fleet_sub.add_parser("secret", help="show, set, or rotate the fleet bus secret")
    add_fleet_common(p_sec)
    _add_manifest_arg(p_sec)
    p_sec.add_argument("--show", action="store_true", help="print secret (default)")
    p_sec.add_argument(
        "--set",
        nargs="?",
        const=True,
        default=None,
        help="set secret (prompt if value omitted)",
    )
    p_sec.add_argument("--rotate", action="store_true", help="generate a new secret")
    p_sec.set_defaults(func=cmd_fleet_secret)

    p_flist = fleet_sub.add_parser("list", help="list robots from presence heartbeats")
    add_fleet_common(p_flist)
    _add_manifest_arg(p_flist)
    _add_secure_arg(p_flist)
    p_flist.add_argument("--ttl", type=float, default=3.0, help="presence TTL seconds")
    p_flist.add_argument("--wait", type=float, default=0.5, help="listen window seconds")
    p_flist.add_argument(
        "--all",
        action="store_true",
        help="in --secure mode: include robots not on the manifest allowlist",
    )
    p_flist.set_defaults(func=cmd_fleet_list)

    p_fwait = fleet_sub.add_parser(
        "wait",
        help="wait until expected robots are present (team bring-up)",
    )
    add_fleet_common(p_fwait)
    _add_manifest_arg(p_fwait)
    _add_secure_arg(p_fwait)
    p_fwait.add_argument(
        "--expect",
        default=None,
        help="comma-separated robot ids (alternative to secure manifest allowlist)",
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
    add_fleet_common(p_ftopics)
    _add_manifest_arg(p_ftopics)
    _add_secure_arg(p_ftopics)
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
    p_ftopics.add_argument(
        "--all",
        action="store_true",
        help="in --secure mode: include topics from robots not on the allowlist",
    )
    p_ftopics.set_defaults(func=cmd_fleet_topics)

    p_festop = fleet_sub.add_parser("estop", help="publish fleet emergency stop")
    add_fleet_common(p_festop)
    _add_manifest_arg(p_festop)
    _add_secure_arg(p_festop)
    p_festop.set_defaults(func=cmd_fleet_estop)

    p_flead = fleet_sub.add_parser("leader", help="get or claim fleet leader")
    add_fleet_common(p_flead)
    _add_manifest_arg(p_flead)
    _add_secure_arg(p_flead)
    p_flead.add_argument("--claim", default=None, help="robot id to claim as leader")
    p_flead.add_argument("--term", type=int, default=1, help="claim term (with --claim)")
    p_flead.add_argument("--wait", type=float, default=0.5, help="listen window when getting")
    p_flead.set_defaults(func=cmd_fleet_leader)
