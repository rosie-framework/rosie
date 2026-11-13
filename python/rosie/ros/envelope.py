"""Command envelope carried beside a CDR payload.

The DDS bridge forwards a topic payload unchanged, so the envelope is a Zenoh
attachment, not extra fields inside the ROS message. A store-and-forward relay
can read ``id``, ``expiry`` (wall-clock seconds), and ``priority`` and drop or
reorder without decoding the payload.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


def command_envelope(
    *,
    priority: str = "interactive",
    ttl_s: float = 2.0,
    command_id: str | None = None,
    now: float | None = None,
) -> bytes:
    stamp = time.time() if now is None else float(now)
    body = {
        "id": command_id or uuid.uuid4().hex,
        "expiry": stamp + float(ttl_s),
        "priority": str(priority),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def parse_envelope(raw: bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(data, dict) or "id" not in data:
        return None
    return data


def envelope_expired(raw: bytes | None, *, now: float | None = None) -> bool:
    """True only when an envelope is present and its expiry has passed."""
    env = parse_envelope(raw)
    if env is None or "expiry" not in env:
        return False
    stamp = time.time() if now is None else float(now)
    try:
        return float(env["expiry"]) < stamp
    except (TypeError, ValueError):
        return False
