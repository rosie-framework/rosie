"""``rosie secret`` — apply host bus secret into robot.yaml / agent.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_secret_apply(args: argparse.Namespace) -> int:
    from rosie.auth import (
        credentials_for,
        resolve_secret_plaintext,
        sync_secret_into_agent_yaml,
        sync_secret_into_robot_yaml,
    )
    from rosie.manifest import resolve_manifest

    path = Path(args.config).expanduser() if args.config else None
    if path is None:
        for name in ("robot.yaml", "agent.yaml"):
            cand = Path.cwd() / name
            if cand.is_file():
                path = cand
                break
    if path is None or not path.is_file():
        print(
            "error: pass --config robot.yaml (or run from a project with robot.yaml / agent.yaml)",
            file=sys.stderr,
        )
        return 2
    path = path.resolve()

    fleet = args.fleet
    manifest = resolve_manifest(
        manifest=args.manifest,
        fleet=fleet,
        allow_empty_robots=True,
        required=False,
    )
    if manifest and not fleet:
        fleet = manifest.fleet

    # secret apply is explicit: read (or create solo) host secret files.
    password = resolve_secret_plaintext(
        secret=args.secret,
        secret_file=args.secret_file,
        fleet=fleet,
        secure=bool(fleet) or bool(args.solo),
        manifest_secret_file=manifest.secret_file if manifest else None,
    )
    if not password:
        print(
            "error: no host secret found "
            "(fleet init --secure / fleet secret --set / router --secure / --secret)",
            file=sys.stderr,
        )
        return 1

    creds = credentials_for(fleet=fleet, password=password)
    assert creds is not None

    try:
        if path.name.lower().startswith("agent"):
            changed = sync_secret_into_agent_yaml(
                path, password=creds.password, user=creds.user
            )
        else:
            changed = sync_secret_into_robot_yaml(
                path, password=creds.password, user=creds.user
            )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if changed:
        print(f"Wrote bus secret → {path}")
    else:
        print(f"Already up to date: {path}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("secret", help="apply host bus secret into robot/agent yaml")
    sec = p.add_subparsers(dest="secret_command")
    p_apply = sec.add_parser("apply", help="write network.fleet_secret into config yaml")
    p_apply.add_argument(
        "--config",
        default=None,
        help="robot.yaml or agent.yaml (default: ./robot.yaml or ./agent.yaml)",
    )
    p_apply.add_argument("--fleet", default=None, help="fleet id for secret lookup")
    p_apply.add_argument("--manifest", default=None, help="fleet manifest path")
    p_apply.add_argument(
        "--solo",
        action="store_true",
        help="use (and create if needed) ~/.rosie/solo/secret",
    )
    p_apply.add_argument("--secret", default=None, help="password override")
    p_apply.add_argument("--secret-file", default=None, help="password file override")
    p_apply.set_defaults(func=cmd_secret_apply)
