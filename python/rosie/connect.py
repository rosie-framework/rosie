"""Connect locator constants and Zenoh client config pairs (no zenoh import)."""

from __future__ import annotations

import os

# Host sessions default to the local router.
DEFAULT_CONNECT = "tcp/127.0.0.1:7447"
AUTO_CONNECT = "auto"
SOFTAP_CONNECT = "tcp/192.168.4.2:7447"


def is_auto_connect(connect: str | None) -> bool:
    """True when the locator means 'discover the router', not a TCP endpoint."""
    if connect is None:
        return False
    return str(connect).strip().lower() in (AUTO_CONNECT, "scout")


def resolve_connect(connect: str | None = None) -> str:
    """constructor arg → ROSIE_CONNECT → local router default.

    ``auto`` / ``scout`` are preserved so callers can run fleet-verified
    discovery. Host tools that should stay on the local router must treat
    ``auto`` as unset before calling this.
    """
    if connect is not None and str(connect).strip():
        return str(connect).strip()
    env = os.environ.get("ROSIE_CONNECT")
    if env is not None and str(env).strip():
        return str(env).strip()
    return DEFAULT_CONNECT


def zenoh_config_pairs(connect: str) -> list[tuple[str, str]]:
    """Pure Zenoh config entries for a client session.

    Explicit locators disable multicast scouting so the topology matches the
    config. ``auto`` omits endpoints and enables scouting (fallback when
    candidate enumeration is unavailable).
    """
    pairs: list[tuple[str, str]] = [("mode", '"client"')]
    if is_auto_connect(connect):
        pairs.append(("scouting/multicast/enabled", "true"))
        return pairs
    pairs.append(("connect/endpoints", f'["{connect}"]'))
    pairs.append(("scouting/multicast/enabled", "false"))
    return pairs
