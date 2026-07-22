"""``rosie fleet`` — discovery, bring-up, and coordination."""

from __future__ import annotations

import argparse
import sys

from rosie.cli._common import add_fleet_common, resolve_fleet_id


def cmd_fleet_list(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = resolve_fleet_id(args)
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

    fleet_id = resolve_fleet_id(args)
    with Fleet(fleet_id, connect=args.connect) as fleet:
        fleet.publish_estop()
        print(f"Published estop on {fleet_id}/_fleet/estop")
    return 0


def cmd_fleet_leader(args: argparse.Namespace) -> int:
    from rosie import Fleet

    fleet_id = resolve_fleet_id(args)
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

    connect = args.connect
    if args.manifest:
        manifest = load_manifest(args.manifest)
        fleet_id = manifest.fleet
        connect = connect or manifest.connect
        expect = manifest
    else:
        fleet_id = resolve_fleet_id(args)
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

    fleet_id = resolve_fleet_id(args)
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


def register(sub: argparse._SubParsersAction) -> None:
    p_fleet = sub.add_parser("fleet", help="fleet discovery, bring-up, and coordination")
    fleet_sub = p_fleet.add_subparsers(dest="fleet_command")

    p_flist = fleet_sub.add_parser("list", help="list robots from presence heartbeats")
    add_fleet_common(p_flist)
    p_flist.add_argument("--ttl", type=float, default=3.0, help="presence TTL seconds")
    p_flist.add_argument("--wait", type=float, default=0.5, help="listen window seconds")
    p_flist.set_defaults(func=cmd_fleet_list)

    p_fwait = fleet_sub.add_parser(
        "wait",
        help="wait until expected robots are present (team bring-up)",
    )
    add_fleet_common(p_fwait)
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
    add_fleet_common(p_ftopics)
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
    add_fleet_common(p_festop)
    p_festop.set_defaults(func=cmd_fleet_estop)

    p_flead = fleet_sub.add_parser("leader", help="get or claim fleet leader")
    add_fleet_common(p_flead)
    p_flead.add_argument("--claim", default=None, help="robot id to claim as leader")
    p_flead.add_argument("--term", type=int, default=1, help="claim term (with --claim)")
    p_flead.add_argument("--wait", type=float, default=0.5, help="listen window when getting")
    p_flead.set_defaults(func=cmd_fleet_leader)
