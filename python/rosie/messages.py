"""Core message helpers: JSON encode/decode and stamp injection."""

from __future__ import annotations

import json
import time
from typing import Any


def stamp_now() -> float:
    """Wall-clock seconds (laptop). MCU uses millis()/1000.0 instead."""
    return time.time()


def encode_json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def decode_json(payload: bytes | str) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def with_stamp(body: dict[str, Any], stamp: float | None = None) -> dict[str, Any]:
    """Return a copy of body with top-level stamp set when missing."""
    out = dict(body)
    if "stamp" not in out or not out["stamp"]:
        out["stamp"] = stamp_now() if stamp is None else stamp
    return out
