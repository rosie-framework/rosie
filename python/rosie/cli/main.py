"""Rosie command-line interface — parser assembly and dispatch."""

from __future__ import annotations

import argparse
import sys

from rosie import __version__
from rosie.cli import (
    bag,
    doctor,
    drive,
    fleet,
    robot,
    router,
    secret,
    setup,
    teleop,
    topic,
    viz,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosie",
        description="Rosie — batteries-included robotics CLI over Zenoh",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    for mod in (
        setup,
        router,
        doctor,
        teleop,
        drive,
        fleet,
        secret,
        topic,
        bag,
        viz,
        robot,
    ):
        mod.register(sub)

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
            "usage: rosie fleet {init,add,remove,secret,list,wait,topics,estop,leader} ...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if args.command == "secret" and not getattr(args, "secret_command", None):
        print("usage: rosie secret apply [--config rosie-bridge.json5] ...", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "topic" and not getattr(args, "topic_command", None):
        print("usage: rosie topic {list,echo} ...", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "bag" and not getattr(args, "bag_command", None):
        print("usage: rosie bag {record,play,info,export} ...", file=sys.stderr)
        raise SystemExit(2)
    if args.command == "robot" and not getattr(args, "robot_command", None):
        print("usage: rosie robot {setup,doctor} ...", file=sys.stderr)
        raise SystemExit(2)

    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
