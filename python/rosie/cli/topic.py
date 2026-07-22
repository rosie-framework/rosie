"""``rosie topic`` — fleet-scoped topic introspection."""

from __future__ import annotations

import argparse

from rosie.cli._common import add_fleet_common, resolve_fleet_id
from rosie.cli.fleet import cmd_fleet_topics


def cmd_topic_list(args: argparse.Namespace) -> int:
    return cmd_fleet_topics(args)


def cmd_topic_echo(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet_id = resolve_fleet_id(args)
    bag.echo_stream(
        fleet=fleet_id,
        key=args.key,
        connect=args.connect,
        max_count=args.count,
        raw=args.raw,
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_topic = sub.add_parser("topic", help="fleet-scoped topic introspection")
    topic_sub = p_topic.add_subparsers(dest="topic_command")

    p_tlist = topic_sub.add_parser("list", help="list topics under a fleet (by robot)")
    add_fleet_common(p_tlist)
    p_tlist.add_argument("--key", default="**", help="selector relative to fleet")
    p_tlist.add_argument("--wait", type=float, default=2.0, help="listen window seconds")
    p_tlist.add_argument("--flat", action="store_true", help="print full keyexprs")
    p_tlist.set_defaults(func=cmd_topic_list)

    p_techo = topic_sub.add_parser("echo", help="print live samples for a fleet key")
    add_fleet_common(p_techo)
    p_techo.add_argument(
        "--key",
        required=True,
        help="key relative to fleet (e.g. */pose, car1/cmd_vel, _fleet/estop)",
    )
    p_techo.add_argument("--count", type=int, default=None, help="stop after N samples")
    p_techo.add_argument("--raw", action="store_true", help="print repr of bytes")
    p_techo.set_defaults(func=cmd_topic_echo)
