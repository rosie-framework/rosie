"""Lightweight fleet-scoped bag record / play (JSONL over Zenoh keys)."""

from __future__ import annotations

import base64
import fnmatch
import gzip
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TextIO

import zenoh

from .fleet import Fleet

_MAGIC = "rosiebag-v1"
_GZIP_MAGIC = b"\x1f\x8b"


@dataclass
class BagRecord:
    t: float
    key: str
    payload: bytes
    encoding: str  # "text" | "b64"


@dataclass
class BagTopicStats:
    key: str
    count: int = 0
    bytes: int = 0


@dataclass
class BagInfo:
    path: str
    fleet: str | None
    selector: str | None
    compressed: bool
    count: int
    bytes: int
    t_min: float | None
    t_max: float | None
    duration_s: float
    topics: list[BagTopicStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


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


def _is_gzip_path(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".gz") or name.endswith(".rosiebag.gz"):
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(2) == _GZIP_MAGIC
    except OSError:
        return False


def _open_bag_write(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
    return path.open("w", encoding="utf-8")


def _open_bag_read(path: Path) -> TextIO:
    if _is_gzip_path(path):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def _key_matches(key: str, pattern: str | None, fleet: str | None) -> bool:
    """Match a Zenoh key against a fleet-relative or absolute glob pattern."""
    if not pattern or pattern in ("*", "**"):
        return True
    key = str(key).strip("/")
    pattern = str(pattern).strip("/")
    # fnmatch ``*`` matches across ``/``; treat ``**`` the same.
    pat = pattern.replace("**", "*")
    if fnmatch.fnmatchcase(key, pat):
        return True
    if fleet:
        fleet = str(fleet).strip("/")
        prefixed = f"{fleet}/{pat}" if not pat.startswith(fleet + "/") else pat
        if fnmatch.fnmatchcase(key, prefixed.replace("**", "*")):
            return True
        if key.startswith(fleet + "/"):
            rel = key[len(fleet) + 1 :]
            if fnmatch.fnmatchcase(rel, pat):
                return True
    return False


def filter_records(
    records: Iterable[BagRecord],
    *,
    start: float | None = None,
    end: float | None = None,
    key: str | None = None,
    fleet: str | None = None,
    t0: float | None = None,
) -> Iterator[BagRecord]:
    """Yield records in ``[start, end]`` seconds from bag ``t0`` matching ``key``.

    ``start`` / ``end`` are relative to the first record's timestamp (or ``t0``
    if provided). Records are assumed time-ordered.
    """
    origin: float | None = t0
    for rec in records:
        if origin is None:
            origin = float(rec.t)
        rel = float(rec.t) - origin
        if start is not None and rel < float(start):
            continue
        if end is not None and rel > float(end):
            break
        if not _key_matches(rec.key, key, fleet):
            continue
        yield rec


def _parse_record_line(line: str) -> BagRecord:
    obj = json.loads(line)
    return BagRecord(
        t=float(obj["t"]),
        key=str(obj["key"]),
        payload=_decode_stored(str(obj["encoding"]), str(obj["payload"])),
        encoding=str(obj["encoding"]),
    )


def open_bag(path: str | Path) -> tuple[dict[str, Any], Iterator[BagRecord]]:
    """Open a ``.rosiebag`` (optionally ``.gz``) and stream records."""
    bag_path = Path(path).expanduser()
    if not bag_path.is_file():
        raise FileNotFoundError(f"bag not found: {bag_path}")

    fh = _open_bag_read(bag_path)
    try:
        header_line = fh.readline()
        if not header_line.strip():
            fh.close()
            raise ValueError(f"empty bag: {bag_path}")
        header = json.loads(header_line)
        if not isinstance(header, dict) or header.get("rosiebag") != _MAGIC:
            fh.close()
            raise ValueError(f"not a rosiebag v1 file: {bag_path}")
    except Exception:
        fh.close()
        raise

    def _gen() -> Iterator[BagRecord]:
        try:
            for line in fh:
                if not line.strip():
                    continue
                yield _parse_record_line(line)
        finally:
            fh.close()

    return header, _gen()


def load_records(
    path: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    key: str | None = None,
    fleet: str | None = None,
) -> tuple[dict[str, Any], list[BagRecord]]:
    """Load records into memory, optionally filtered."""
    header, it = open_bag(path)
    fleet_id = fleet or header.get("fleet")
    return header, list(
        filter_records(it, start=start, end=end, key=key, fleet=fleet_id)
    )


def _iter_records(path: Path) -> tuple[dict[str, Any], list[BagRecord]]:
    """Backward-compatible full load (used by older callers / tests)."""
    return load_records(path)


def record(
    *,
    fleet: str,
    output: str | Path,
    selector: str = "**",
    connect: str | None = None,
    duration: float | None = None,
    on_sample: Callable[[str, bytes], None] | None = None,
    type_map: dict[str, str] | None = None,
) -> int:
    """Record samples under a fleet until KeyboardInterrupt or ``duration``.

    Write ``.rosiebag.gz`` when the output path ends with ``.gz``.
    """
    out_path = Path(output).expanduser()
    count = 0
    lock = threading.Lock()
    stop_at = time.time() + float(duration) if duration is not None else None

    with Fleet(fleet, connect=connect) as f, _open_bag_write(out_path) as fh:
        header = {"rosiebag": _MAGIC, "fleet": f.fleet, "selector": selector}
        if type_map:
            header["types"] = dict(type_map)
        fh.write(json.dumps(header) + "\n")
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
            how = f"{duration:g}s" if duration is not None else "Ctrl+C to stop"
            print(f"Recording {key} → {out_path} ({how})", file=sys.stderr)
            while True:
                if stop_at is not None and time.time() >= stop_at:
                    break
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


def info(path: str | Path) -> BagInfo:
    """Summarize a bag (streamed; gzip-transparent)."""
    bag_path = Path(path).expanduser()
    header, it = open_bag(bag_path)
    topics: dict[str, BagTopicStats] = {}
    count = 0
    total_bytes = 0
    t_min: float | None = None
    t_max: float | None = None
    for rec in it:
        count += 1
        n = len(rec.payload)
        total_bytes += n
        t = float(rec.t)
        if t_min is None or t < t_min:
            t_min = t
        if t_max is None or t > t_max:
            t_max = t
        st = topics.get(rec.key)
        if st is None:
            st = BagTopicStats(key=rec.key)
            topics[rec.key] = st
        st.count += 1
        st.bytes += n
    duration = (t_max - t_min) if t_min is not None and t_max is not None else 0.0
    topic_list = sorted(topics.values(), key=lambda s: (-s.count, s.key))
    return BagInfo(
        path=str(bag_path),
        fleet=header.get("fleet"),
        selector=header.get("selector"),
        compressed=_is_gzip_path(bag_path),
        count=count,
        bytes=total_bytes,
        t_min=t_min,
        t_max=t_max,
        duration_s=duration,
        topics=topic_list,
    )


def format_info(bi: BagInfo, *, json_out: bool = False) -> str:
    if json_out:
        return json.dumps(bi.to_dict(), indent=2)
    lines = [
        f"path:       {bi.path}",
        f"fleet:      {bi.fleet or '—'}",
        f"selector:   {bi.selector or '—'}",
        f"compressed: {bi.compressed}",
        f"samples:    {bi.count}",
        f"bytes:      {bi.bytes}",
        f"duration:   {bi.duration_s:.3f} s",
    ]
    if bi.t_min is not None and bi.t_max is not None:
        lines.append(f"t_range:    {bi.t_min:.3f} … {bi.t_max:.3f}")
    lines.append("topics:")
    if not bi.topics:
        lines.append("  (none)")
    else:
        for st in bi.topics:
            lines.append(f"  {st.count:6d}  {st.bytes:8d} B  {st.key}")
    return "\n".join(lines)


def play(
    path: str | Path,
    *,
    connect: str | None = None,
    rate: float = 1.0,
    fleet: str | None = None,
    start: float | None = None,
    end: float | None = None,
    key: str | None = None,
) -> int:
    """Replay a bag onto the bus. Returns number of samples published.

    ``start`` / ``end`` are seconds from the bag's first timestamp.
    ``key`` is a fleet-relative or absolute glob (e.g. ``'*/pose'``).
    """
    bag_path = Path(path).expanduser()
    header, it = open_bag(bag_path)
    fleet_id = fleet or header.get("fleet") or os.environ.get("ROSIE_FLEET")
    if not fleet_id:
        raise ValueError("fleet id required (bag header, --fleet, or ROSIE_FLEET)")

    rate = max(1e-6, float(rate))
    count = 0
    t0_play: float | None = None
    t0_wall = 0.0

    with Fleet(str(fleet_id), connect=connect) as f:
        print(
            f"Playing {bag_path} (rate={rate}) on fleet {f.fleet}",
            file=sys.stderr,
        )
        for rec in filter_records(
            it, start=start, end=end, key=key, fleet=fleet_id
        ):
            if t0_play is None:
                t0_play = float(rec.t)
                t0_wall = time.time()
            target = t0_wall + (float(rec.t) - t0_play) / rate
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)
            f.session.put(rec.key, rec.payload)
            count += 1

    if count == 0:
        print("No samples match filters.", file=sys.stderr)
    else:
        print(f"Played {count} sample(s)", file=sys.stderr)
    return count


def export_mcap(
    path: str | Path,
    output: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    key: str | None = None,
    fleet: str | None = None,
) -> int:
    """Export a ``.rosiebag`` to MCAP for Foxglove / Python analysis.

    Requires the ``mcap`` package (installed with Rosie core).
    """
    try:
        from mcap.writer import Writer
    except ImportError as e:
        raise ImportError(
            "rosie bag export requires the mcap package.\n"
            '  pip install "rosie-framework"   # or: pip install mcap'
        ) from e

    bag_path = Path(path).expanduser()
    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header, it = open_bag(bag_path)
    fleet_id = fleet or header.get("fleet")

    channels: dict[str, int] = {}
    schema_json: int | None = None
    schema_bytes: int | None = None
    schema_jpeg: int | None = None
    count = 0

    with out_path.open("wb") as fh:
        writer = Writer(fh)
        writer.start(profile="", library="rosie")

        for rec in filter_records(
            it, start=start, end=end, key=key, fleet=fleet_id
        ):
            topic = rec.key
            ros_type = (header.get("types") or {}).get(topic)
            if topic not in channels and ros_type:
                from .ros.schemas import schema_bytes as ros_schema_bytes

                schema_id = writer.register_schema(
                    name=ros_type,
                    encoding="ros2msg",
                    data=ros_schema_bytes(ros_type),
                )
                channels[topic] = writer.register_channel(
                    topic=topic,
                    message_encoding="cdr",
                    schema_id=schema_id,
                )
            if topic not in channels:
                if rec.encoding == "text":
                    if schema_json is None:
                        schema_json = writer.register_schema(
                            name="rosie.json",
                            encoding="jsonschema",
                            data=b'{"type":"object"}',
                        )
                    channels[topic] = writer.register_channel(
                        topic=topic,
                        message_encoding="json",
                        schema_id=schema_json,
                    )
                elif "camera/compressed" in topic:
                    if schema_jpeg is None:
                        schema_jpeg = writer.register_schema(
                            name="rosie.jpeg",
                            encoding="",
                            data=b"",
                        )
                    channels[topic] = writer.register_channel(
                        topic=topic,
                        message_encoding="jpeg",
                        schema_id=schema_jpeg,
                    )
                else:
                    if schema_bytes is None:
                        schema_bytes = writer.register_schema(
                            name="rosie.bytes",
                            encoding="",
                            data=b"",
                        )
                    channels[topic] = writer.register_channel(
                        topic=topic,
                        message_encoding="application/octet-stream",
                        schema_id=schema_bytes,
                    )
            ns = int(float(rec.t) * 1e9)
            writer.add_message(
                channel_id=channels[topic],
                log_time=ns,
                data=rec.payload,
                publish_time=ns,
            )
            count += 1
        writer.finish()

    if count == 0:
        print("No samples match filters.", file=sys.stderr)
        if out_path.is_file():
            out_path.unlink(missing_ok=True)
    else:
        print(f"Wrote {count} message(s) to {out_path}", file=sys.stderr)
    return count


def echo_stream(
    *,
    fleet: str,
    key: str,
    connect: str | None = None,
    max_count: int | None = None,
    raw: bool = False,
    out: TextIO | None = None,
    ros_type: str | None = None,
    distro: str = "jazzy",
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
            elif ros_type and raw_bytes[:1:] != b"{":
                try:
                    from .ros.codec import decode

                    decoded = decode(ros_type, raw_bytes, distro=distro)
                    out.write(f"[{k}] {json.dumps(decoded)}\n")
                except Exception:
                    out.write(f"[{k}] <{len(raw_bytes)} bytes {ros_type}>\n")
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
