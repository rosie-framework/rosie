"""Lightweight fleet-scoped bag record / play (JSONL over Zenoh keys)."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import zenoh

from .fleet import Fleet

_MAGIC = "rosiebag-v1"


@dataclass
class BagRecord:
    t: float
    key: str
    payload: bytes
    encoding: str  # "text" | "b64"


def _classify_payload(raw: bytes) -> tuple[str, str]:
    """Return (encoding, stored_payload_string)."""
    try:
        text = raw.decode("utf-8")
        # Prefer text when valid UTF-8 (JSON or log lines).
        return "text", text
    except UnicodeDecodeError:
        return "b64", base64.b64encode(raw).decode("ascii")


def _decode_stored(encoding: str, stored: str) -> bytes:
    if encoding == "text":
        return stored.encode("utf-8")
    if encoding == "b64":
        return base64.b64decode(stored)
    raise ValueError(f"unknown bag encoding: {encoding!r}")


def record(
    *,
    fleet: str,
    output: str | Path,
    selector: str = "**",
    connect: str | None = None,
    on_sample: Callable[[str, bytes], None] | None = None,
) -> int:
    """Record samples under a fleet until KeyboardInterrupt. Returns count."""
    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    lock = threading.Lock()

    with Fleet(fleet, connect=connect) as f, out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"rosiebag": _MAGIC, "fleet": f.fleet, "selector": selector}) + "\n")
        fh.flush()
        key = f.resolve_key(selector)

        def _on(sample: zenoh.Sample) -> None:
            nonlocal count
            try:
                k = str(sample.key_expr)
                raw = sample.payload.to_bytes()
            except Exception:
                return
            enc, stored = _classify_payload(raw)
            line = json.dumps({"t": time.time(), "key": k, "encoding": enc, "payload": stored})
            with lock:
                fh.write(line + "\n")
                fh.flush()
                count += 1
            if on_sample:
                on_sample(k, raw)

        sub = f.session.declare_subscriber(key, _on)
        try:
            print(f"Recording {key} → {out_path} (Ctrl+C to stop)", file=sys.stderr)
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            print(file=sys.stderr)
        finally:
            try:
                sub.undeclare()
            except Exception:
                pass

    print(f"Wrote {count} sample(s) to {out_path}", file=sys.stderr)
    return count


def _iter_records(path: Path) -> tuple[dict[str, Any], list[BagRecord]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"empty bag: {path}")
    header = json.loads(lines[0])
    if not isinstance(header, dict) or header.get("rosiebag") != _MAGIC:
        raise ValueError(f"not a rosiebag v1 file: {path}")
    records: list[BagRecord] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        obj = json.loads(line)
        records.append(
            BagRecord(
                t=float(obj["t"]),
                key=str(obj["key"]),
                payload=_decode_stored(str(obj["encoding"]), str(obj["payload"])),
                encoding=str(obj["encoding"]),
            )
        )
    return header, records


def play(
    path: str | Path,
    *,
    connect: str | None = None,
    rate: float = 1.0,
    fleet: str | None = None,
) -> int:
    """Replay a bag onto the bus. Returns number of samples published."""
    bag_path = Path(path).expanduser()
    if not bag_path.is_file():
        raise FileNotFoundError(f"bag not found: {bag_path}")
    header, records = _iter_records(bag_path)
    if not records:
        print("Bag has no samples.", file=sys.stderr)
        return 0

    fleet_id = fleet or header.get("fleet") or os.environ.get("ROSIE_FLEET")
    if not fleet_id:
        raise ValueError("fleet id required (bag header, --fleet, or ROSIE_FLEET)")

    rate = max(1e-6, float(rate))
    t0_bag = records[0].t
    t0_wall = time.time()

    with Fleet(str(fleet_id), connect=connect) as f:
        print(
            f"Playing {bag_path} ({len(records)} samples, rate={rate}) "
            f"on fleet {f.fleet}",
            file=sys.stderr,
        )
        for rec in records:
            target = t0_wall + (rec.t - t0_bag) / rate
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)
            f.session.put(rec.key, rec.payload)
    return len(records)


def echo_stream(
    *,
    fleet: str,
    key: str,
    connect: str | None = None,
    max_count: int | None = None,
    raw: bool = False,
    out: TextIO | None = None,
) -> int:
    """Subscribe and print samples until KeyboardInterrupt or max_count."""
    out = out or sys.stdout
    count = 0
    with Fleet(fleet, connect=connect) as f:
        selector = f.resolve_key(key)

        def _on(sample: zenoh.Sample) -> None:
            nonlocal count
            try:
                k = str(sample.key_expr)
                raw_bytes = sample.payload.to_bytes()
            except Exception:
                return
            if raw:
                out.write(f"[{k}] {raw_bytes!r}\n")
            else:
                try:
                    text = raw_bytes.decode("utf-8")
                    out.write(f"[{k}] {text}\n")
                except UnicodeDecodeError:
                    out.write(f"[{k}] <{len(raw_bytes)} bytes>\n")
            out.flush()
            count += 1

        sub = f.session.declare_subscriber(selector, _on)
        try:
            print(f"Echoing {selector} (Ctrl+C to stop)", file=sys.stderr)
            while max_count is None or count < max_count:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print(file=sys.stderr)
        finally:
            try:
                sub.undeclare()
            except Exception:
                pass
    return count
