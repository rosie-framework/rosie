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


def zenoh_config_pairs(connect: str, mode: str = "client") -> list[tuple[str, str]]:
    """Zenoh config entries for ``client``, ``peer``, or ``router``.

    Explicit locators disable multicast scouting so the topology matches the
    config. ``auto`` omits endpoints and enables scouting (fallback when
    candidate enumeration is unavailable). ``peer`` and ``router`` also listen
    so a robot can run without a fleet router.
    """
    mode = str(mode or "client").strip().lower()
    if mode not in ("client", "peer", "router"):
        raise ValueError("mode must be client, peer, or router")
    pairs: list[tuple[str, str]] = [("mode", f'"{mode}"')]
    if mode in ("peer", "router"):
        pairs.append(("listen/endpoints", '["tcp/0.0.0.0:7447"]'))
    if is_auto_connect(connect):
        pairs.append(("scouting/multicast/enabled", "true"))
        return pairs
    if connect:
        pairs.append(("connect/endpoints", f'["{connect}"]'))
    pairs.append(("scouting/multicast/enabled", "false"))
    return pairs
