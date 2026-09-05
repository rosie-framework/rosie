"""``rosie viz`` — lightweight browser spatial viewer."""

from __future__ import annotations

import argparse
import os
import sys


def cmd_viz(args: argparse.Namespace) -> int:
    from rosie.tools.viz.bridge import VizBridge
    from rosie.tools.viz.server import run_server

    bridge = VizBridge(stale_s=args.stale)
    try:
        if args.bag:
            bridge.start_bag(
                args.bag,
                fleet=args.fleet,
                connect=args.connect,
                rate=args.rate,
                start=args.start,
                end=args.end,
                key=args.key,
            )
        else:
            fleet = args.fleet
            if not fleet:
                print(
                    "error: --fleet or ROSIE_FLEET is required (or pass --bag)",
                    file=sys.stderr,
                )
                return 2
            bridge.start_live(fleet=fleet, connect=args.connect)
        run_server(
            bridge,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        bridge.close()
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "viz",
        help="lightweight browser spatial viewer (poses / trails / optional bag)",
    )
    p.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="fleet id (default: ROSIE_FLEET)",
    )
    p.add_argument(
        "--robot",
        default=os.environ.get("ROSIE_ROBOT"),
        help="unused for live (fleet view); kept for bag filters / compatibility",
    )
    p.add_argument("--connect", default=None, help="override ROSIE_CONNECT")
    p.add_argument(
        "--bag",
        default=None,
        help="replay a .rosiebag in the viewer (offline scrub)",
    )
    p.add_argument("--rate", type=float, default=1.0, help="bag playback rate")
    p.add_argument(
        "--start",
        type=float,
        default=None,
        help="bag: seconds from t0 to start (inclusive)",
    )
    p.add_argument(
        "--end",
        type=float,
        default=None,
        help="bag: seconds from t0 to end (inclusive)",
    )
    p.add_argument(
        "--key",
        default=None,
        help="bag: topic glob (fleet-relative or absolute), e.g. '*/pose'",
    )
    p.add_argument("--host", default="127.0.0.1", help="bind address")
    p.add_argument("--port", type=int, default=8765, help="HTTP port (default 8765)")
    p.add_argument(
        "--stale",
        type=float,
        default=3.0,
        help="seconds before a live pose is marked stale",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab",
    )
    p.set_defaults(func=cmd_viz)
