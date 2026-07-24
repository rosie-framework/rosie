"""Shared fleet / solo Zenoh usrpwd secrets and config helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .fleet_home import (
    SOLO_USER,
    default_secret_path,
    generate_secret,
    read_secret_file,
    solo_secret_path,
    write_secret_file,
)

BusMode = Literal["solo-open", "solo-secure", "fleet-open", "fleet-secure"]


def sha256_hex(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def bus_mode(*, fleet: str | None, secure: bool) -> BusMode:
    """Return the four-mode label for banners and docs."""
    if fleet:
        return "fleet-secure" if secure else "fleet-open"
    return "solo-secure" if secure else "solo-open"


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

    Host secret files (manifest ``secret_file``, ``~/.rosie/fleets/<id>/secret``,
    ``~/.rosie/solo/secret``) are read **only when** ``secure=True``. Presence of
    a leftover secret file must not silently enable auth on an open bus.
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

    # Solo secure: read or create ~/.rosie/solo/secret
    got = read_secret_file(solo_secret_path())
    if got:
        return got
    s = generate_secret()
    write_secret_file(solo_secret_path(), s)
    return s


def credentials_for(
    *,
    fleet: str | None,
    password: str | None,
) -> BusCredentials | None:
    if not password:
        return None
    user = fleet.strip() if fleet else SOLO_USER
    if not user:
        user = SOLO_USER
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
    fleet: str | None,
    password: str,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write credentials dictionary + router json5; return (config, dictionary)."""
    from .bootstrap import rosie_home

    creds = credentials_for(fleet=fleet, password=password)
    assert creds is not None
    label = fleet or "solo"
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


def sync_secret_into_robot_yaml(
    yaml_path: Path,
    *,
    password: str,
    user: str,
) -> bool:
    """Write ``network.fleet_secret`` / ``network.user`` into robot.yaml. Return True if changed."""
    import yaml

    path = Path(yaml_path).expanduser().resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping at top level")
    net = dict(data.get("network") or {})
    before = (net.get("user"), net.get("fleet_secret"))
    net["user"] = user
    net["fleet_secret"] = password
    if before == (net["user"], net["fleet_secret"]):
        return False
    data["network"] = net
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return True


def sync_secret_into_agent_yaml(
    yaml_path: Path,
    *,
    password: str,
    user: str,
) -> bool:
    """Write top-level ``user`` / ``fleet_secret`` into agent.yaml. Return True if changed."""
    import yaml

    path = Path(yaml_path).expanduser().resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping at top level")
    before = (data.get("user"), data.get("fleet_secret"))
    data["user"] = user
    data["fleet_secret"] = password
    if before == (data["user"], data["fleet_secret"]):
        return False
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return True


def maybe_sync_secret_for_robot_config(yaml_path: Path, raw: dict[str, Any]) -> bool:
    """Sync host secret into robot.yaml only when the yaml already has a secret.

    Open-bus builds must not pull ``~/.rosie/.../secret`` just because the file
    exists. Use ``rosie secret apply`` (or keep an existing ``fleet_secret`` in
    yaml) for secure MCU configs.
    """
    fleet = raw.get("fleet")
    if fleet is False or fleet == "":
        fleet = None
    elif fleet is not None:
        fleet = str(fleet).strip() or None
    net = raw.get("network") or {}
    existing = net.get("fleet_secret")
    if not existing:
        return False
    password = resolve_secret_plaintext(fleet=fleet, secure=True)
    if not password:
        return False
    creds = credentials_for(fleet=fleet, password=password)
    assert creds is not None
    return sync_secret_into_robot_yaml(yaml_path, password=creds.password, user=creds.user)


def maybe_sync_secret_for_agent_config(yaml_path: Path, raw: dict[str, Any]) -> bool:
    """Sync host secret into agent.yaml only when yaml already has fleet_secret."""
    fleet = raw.get("fleet")
    if fleet is False or fleet == "":
        fleet = None
    elif fleet is not None:
        fleet = str(fleet).strip() or None
    if not raw.get("fleet_secret"):
        return False
    password = resolve_secret_plaintext(fleet=fleet, secure=True)
    if not password:
        return False
    creds = credentials_for(fleet=fleet, password=password)
    assert creds is not None
    return sync_secret_into_agent_yaml(yaml_path, password=creds.password, user=creds.user)
