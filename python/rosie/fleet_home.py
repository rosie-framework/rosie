"""Host-side fleet and solo secret/manifest paths under ``~/.rosie``."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from .bootstrap import rosie_home

SOLO_USER = "rosie"


def fleets_root() -> Path:
    return rosie_home() / "fleets"


def fleet_dir(fleet_id: str) -> Path:
    fleet_id = str(fleet_id).strip().strip("/")
    if not fleet_id or "/" in fleet_id:
        raise ValueError(f"invalid fleet id: {fleet_id!r}")
    return fleets_root() / fleet_id


def default_manifest_path(fleet_id: str) -> Path:
    return fleet_dir(fleet_id) / "manifest.yaml"


def default_secret_path(fleet_id: str) -> Path:
    return fleet_dir(fleet_id) / "secret"


def solo_dir() -> Path:
    return rosie_home() / "solo"


def solo_secret_path() -> Path:
    return solo_dir() / "secret"


def ensure_dir(path: Path, *, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def write_secret_file(path: Path, secret: str) -> Path:
    path = Path(path).expanduser()
    ensure_dir(path.parent)
    path.write_text(secret.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_secret_file(path: Path) -> str | None:
    path = Path(path).expanduser()
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def generate_secret(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
