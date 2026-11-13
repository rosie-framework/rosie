"""Shared fleet Zenoh usrpwd secrets and config helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .fleet_home import (
    default_secret_path,
    read_secret_file,
)

BusMode = Literal["fleet-open", "fleet-secure"]


def sha256_hex(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def bus_mode(*, fleet: str | None, secure: bool) -> BusMode:
    """Return the bus-mode label for banners and docs."""
    if not fleet:
        raise ValueError("fleet is required")
    return "fleet-secure" if secure else "fleet-open"


@dataclass(frozen=True)
class BusCredentials:
    """Zenoh usrpwd identity for clients and router dictionary entries."""

    user: str
    password: str  # plaintext (hash applied when writing zenoh configs)

    @property
    def password_hash(self) -> str:
        return sha256_hex(self.password)


def resolve_secret_plaintext(
    *,
    secret: str | None = None,
    secret_file: str | Path | None = None,
    fleet: str | None = None,
    secure: bool = False,
    manifest_secret_file: str | Path | None = None,
) -> str | None:
    """Resolve bus password (plaintext).

    Explicit overrides always win: ``secret`` → ``secret_file`` →
    ``ROSIE_FLEET_SECRET``.

    Host secret files (manifest ``secret_file``, ``~/.rosie/fleets/<id>/secret``)
    are read **only when** ``secure=True``. Presence of a leftover secret file
    must not silently enable auth on an open bus.
    """
    if secret is not None and str(secret).strip():
        return str(secret).strip()
    if secret_file is not None:
        got = read_secret_file(Path(secret_file))
        if got:
            return got
    env = os.environ.get("ROSIE_FLEET_SECRET")
    if env and env.strip():
        return env.strip()

    if not secure:
        return None

    if manifest_secret_file is not None:
        got = read_secret_file(Path(manifest_secret_file))
        if got:
            return got
    if fleet:
        got = read_secret_file(default_secret_path(fleet))
        if got:
            return got
    return None


def credentials_for(
    *,
    fleet: str | None,
    password: str | None,
) -> BusCredentials | None:
    if not password:
        return None
    user = (fleet or "").strip()
    if not user:
        raise ValueError("fleet is required for bus credentials")
    return BusCredentials(user=user, password=password)


def apply_usrpwd_to_zenoh_config(conf: Any, creds: BusCredentials) -> None:
    """Insert transport.auth.usrpwd into an open ``zenoh.Config``."""
    # Prefer nested JSON5 inserts used by eclipse-zenoh Python bindings.
    conf.insert_json5("transport/auth/usrpwd/user", json.dumps(creds.user))
    conf.insert_json5(
        "transport/auth/usrpwd/password", json.dumps(creds.password_hash)
    )


def write_router_auth_files(
    *,
    fleet: str,
    password: str,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write credentials dictionary + router json5; return (config, dictionary)."""
    from .bootstrap import rosie_home

    creds = credentials_for(fleet=fleet, password=password)
    assert creds is not None
    label = fleet
    root = Path(out_dir) if out_dir else (rosie_home() / "router" / label)
    root.mkdir(parents=True, exist_ok=True)
    dictionary = root / "credentials.txt"
    config = root / "zenoh-auth.json5"
    # Router's own usrpwd + dictionary of allowed clients (same shared secret).
    dictionary.write_text(
        f"{creds.user}:{creds.password_hash}\n",
        encoding="utf-8",
    )
    try:
        os.chmod(dictionary, 0o600)
    except OSError:
        pass
    # Router identity can reuse the same user/password hash.
    dict_path = str(dictionary.resolve()).replace("\\", "/")
    text = (
        "{\n"
        '  listen: { endpoints: ["tcp/0.0.0.0:7447"] },\n'
        "  transport: {\n"
        "    auth: {\n"
        "      usrpwd: {\n"
        f'        user: "{creds.user}",\n'
        f'        password: "{creds.password_hash}",\n'
        f'        dictionary_file: "{dict_path}",\n'
        "      },\n"
        "    },\n"
        "  },\n"
        "}\n"
    )
    config.write_text(text, encoding="utf-8")
    try:
        os.chmod(config, 0o600)
    except OSError:
        pass
    return config, dictionary

