"""``rosie bag`` — record/play/inspect/export fleet traffic."""

from __future__ import annotations

import argparse
import os
import sys

from rosie.cli._common import add_fleet_common, resolve_fleet_id


def _add_slice_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--start",
        type=float,
        default=None,
        help="seconds from bag t0 to start (inclusive)",
    )
    p.add_argument(
        "--end",
        type=float,
        default=None,
        help="seconds from bag t0 to end (inclusive)",
    )
    p.add_argument(
        "--key",
        default=None,
        help="topic glob (fleet-relative or absolute), e.g. '*/pose'",
    )


def cmd_bag_record(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet_id = resolve_fleet_id(args)

    def _progress(key: str, _raw: bytes) -> None:
        if args.verbose:
            print(key, file=sys.stderr)

    bag.record(
        fleet=fleet_id,
        output=args.output,
        selector=args.key,
        connect=args.connect,
        duration=args.duration,
        on_sample=_progress if args.verbose else None,
    )
    return 0


def cmd_bag_play(args: argparse.Namespace) -> int:
    from rosie import bag

    fleet = args.fleet or os.environ.get("ROSIE_FLEET")
    try:
        bag.play(
            args.bag,
            connect=args.connect,
            rate=args.rate,
            fleet=fleet,
            start=args.start,
            end=args.end,
            key=args.key,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_bag_info(args: argparse.Namespace) -> int:
    from rosie import bag

    try:
        bi = bag.info(args.bag)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(bag.format_info(bi, json_out=args.json))
    return 0


def cmd_bag_export(args: argparse.Namespace) -> int:
    from rosie import bag

    try:
        bag.export_mcap(
            args.bag,
            args.output,
            start=args.start,
            end=args.end,
            key=args.key,
            fleet=args.fleet or os.environ.get("ROSIE_FLEET"),
        )
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p_bag = sub.add_parser("bag", help="record/play/inspect fleet traffic from the router host")
    bag_sub = p_bag.add_subparsers(dest="bag_command")

    p_brec = bag_sub.add_parser("record", help="record fleet topics to a .rosiebag file")
    add_fleet_common(p_brec)
    p_brec.add_argument(
        "-o",
        "--output",
        required=True,
        help="output path (.rosiebag or .rosiebag.gz)",
    )
    p_brec.add_argument(
        "--key",
        default="**",
        help="selector relative to fleet (default: **)",
    )
    p_brec.add_argument(
        "--duration",
        type=float,
        default=None,
        help="stop after this many seconds (default: until Ctrl+C)",
    )
    p_brec.add_argument("-v", "--verbose", action="store_true", help="print keys as recorded")
    p_brec.set_defaults(func=cmd_bag_record)

    p_bplay = bag_sub.add_parser("play", help="replay a .rosiebag onto the bus")
    p_bplay.add_argument("bag", help="path to .rosiebag[.gz]")
    p_bplay.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="override fleet id (default: bag header / ROSIE_FLEET)",
    )
    p_bplay.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p_bplay.add_argument("--rate", type=float, default=1.0, help="playback rate multiplier")
    _add_slice_args(p_bplay)
    p_bplay.set_defaults(func=cmd_bag_play)

    p_binfo = bag_sub.add_parser("info", help="summarize a .rosiebag")
    p_binfo.add_argument("bag", help="path to .rosiebag[.gz]")
    p_binfo.add_argument("--json", action="store_true", help="print JSON")
    p_binfo.set_defaults(func=cmd_bag_info)

    p_bexp = bag_sub.add_parser(
        "export",
        help="export a .rosiebag to MCAP",
    )
    p_bexp.add_argument("bag", help="path to .rosiebag[.gz]")
    p_bexp.add_argument(
        "-o",
        "--output",
        required=True,
        help="output .mcap path",
    )
    p_bexp.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="fleet id for key matching (default: bag header / ROSIE_FLEET)",
    )
    _add_slice_args(p_bexp)
    p_bexp.set_defaults(func=cmd_bag_export)
