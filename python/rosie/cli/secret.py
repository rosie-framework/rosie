"""``rosie secret`` — apply the host bus secret into an agent or bridge config."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def cmd_secret_apply(args: argparse.Namespace) -> int:
    from rosie.auth import (
        credentials_for,
        resolve_secret_plaintext,
        sha256_hex,
    )
    from rosie.manifest import resolve_manifest

    path = Path(args.config).expanduser() if args.config else None
    if path is None:
        for name in ("rosie-bridge.json5",):
            cand = Path.cwd() / name
            if cand.is_file():
                path = cand
                break
    if path is None or not path.is_file():
        print(
            "error: pass --config rosie-bridge.json5",
            file=sys.stderr,
        )
        return 2
    path = path.resolve()

    fleet = args.fleet or os.environ.get("ROSIE_FLEET")
    manifest = resolve_manifest(
        manifest=args.manifest,
        fleet=fleet,
        allow_empty_robots=True,
        required=False,
    )
    if manifest and not fleet:
        fleet = manifest.fleet
    if not fleet:
        print("error: --fleet or ROSIE_FLEET is required", file=sys.stderr)
        return 2

    password = resolve_secret_plaintext(
        secret=args.secret,
        secret_file=args.secret_file,
        fleet=fleet,
        secure=True,
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
        if path.suffix not in {".json5", ".json"}:
            print("error: --config must be a bridge json5 file", file=sys.stderr)
            return 2
        changed = _sync_secret_into_bridge(path, user=creds.user, password=creds.password)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if changed:
        print(f"Wrote bus secret → {path}")
    else:
        print(f"Already up to date: {path}")
    return 0


def _sync_secret_into_bridge(path: Path, *, user: str, password: str) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    block = data.setdefault("transport", {}).setdefault("auth", {}).setdefault("usrpwd", {})
    hashed = sha256_hex(password)
    before = (block.get("user"), block.get("password"))
    block["user"] = user
    block["password"] = hashed
    if before == (user, hashed):
        return False
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("secret", help="apply the host bus secret into a robot config")
    sec = p.add_subparsers(dest="secret_command")
    p_apply = sec.add_parser("apply", help="write usrpwd credentials into a bridge or agent config")
    p_apply.add_argument(
        "--config",
        default=None,
        help="rosie-bridge.json5 from `rosie robot setup`",
    )
    p_apply.add_argument(
        "--fleet",
        default=os.environ.get("ROSIE_FLEET"),
        help="fleet id for secret lookup (default: ROSIE_FLEET)",
    )
    p_apply.add_argument("--manifest", default=None, help="fleet manifest path")
    p_apply.add_argument("--secret", default=None, help="password override")
    p_apply.add_argument("--secret-file", default=None, help="password file override")
    p_apply.set_defaults(func=cmd_secret_apply)
