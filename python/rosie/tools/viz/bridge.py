"""Live / bag pose state for ``rosie viz``."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import zenoh

from rosie import topics
from rosie.messages import decode_json
from rosie.session import Qos, Session


def _robot_and_rel(key: str, fleet: str | None) -> tuple[str | None, str]:
    """Parse ``{fleet}/{robot}/{rel}`` or ``{robot}/{rel}`` → (robot, rel)."""
    parts = [p for p in str(key).strip("/").split("/") if p]
    if not parts:
        return None, ""
    if fleet and len(parts) >= 2 and parts[0] == fleet:
        robot = parts[1]
        if robot == "_fleet":
            return None, "/".join(parts[2:])
        return robot, "/".join(parts[2:])
    if len(parts) >= 2:
        return parts[0], "/".join(parts[1:])
    return None, parts[0]


class VizBridge:
    """Thread-safe pose/camera store fed by live Zenoh or bag playback."""

    def __init__(self, *, stale_s: float = 3.0, trail_max: int = 200) -> None:
        self.stale_s = float(stale_s)
        self.trail_max = int(trail_max)
        self._lock = threading.Lock()
        self._robots: dict[str, dict[str, Any]] = {}
        self._trails: dict[str, list[tuple[float, float]]] = {}
        self._jpeg: dict[str, bytes] = {}
        self._jpeg_b64: str | None = None
        self._jpeg_b64_robot: str | None = None
        self._jpeg_b64_t: float = 0.0
        self._jpeg_hz: float = 8.0
        self._selected: str | None = None
        self._subs: list[Any] = []
        self._fleet_obj: Any | None = None
        self._session: Session | None = None
        self._cam_session: Session | None = None
        self._fleet: str | None = None
        self._connect: str | None = None
        self._mode: str = "idle"
        self._bag_thread: threading.Thread | None = None
        self._bag_stop = threading.Event()
        self._bag_pause = threading.Event()
        self._bag_pause.set()
        self._bag_records: list[Any] = []
        self._bag_index = 0
        self._bag_rate = 1.0
        self._bag_t0 = 0.0
        self._bag_wall0 = 0.0
        self._bag_seek_t: float | None = None
        self._bag_path: str | None = None
        self._cam_robot: str | None = None

    def close(self) -> None:
        self._bag_stop.set()
        self._bag_pause.set()
        if self._bag_thread and self._bag_thread.is_alive():
            self._bag_thread.join(timeout=2.0)
        for s in self._subs:
            try:
                s.undeclare()
            except Exception:
                pass
        self._subs.clear()
        if self._cam_session is not None:
            self._cam_session.close()
            self._cam_session = None
        if self._session is not None:
            self._session.close()
            self._session = None
        if self._fleet_obj is not None:
            self._fleet_obj.close()
            self._fleet_obj = None

    def select_robot(self, robot: str | None) -> None:
        with self._lock:
            self._selected = robot
        if self._mode == "live" and robot:
            self._ensure_camera_sub(robot)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            robots: dict[str, Any] = {}
            for rid, pose in self._robots.items():
                age = now - float(pose.get("t", now))
                stale = age > self.stale_s and self._mode == "live"
                if stale and age > self.stale_s * 3:
                    continue
                entry = dict(pose)
                entry["trail"] = list(self._trails.get(rid, []))
                entry["stale"] = stale
                robots[rid] = entry
            selected = self._selected
            jpeg_b64 = self._throttled_jpeg_b64(selected, now)
            bag = None
            if self._mode == "bag" and self._bag_records:
                t_min = float(self._bag_records[0].t)
                t_max = float(self._bag_records[-1].t)
                idx = min(self._bag_index, len(self._bag_records) - 1)
                cur = float(self._bag_records[idx].t)
                bag = {
                    "path": self._bag_path,
                    "t_min": t_min,
                    "t_max": t_max,
                    "t": cur,
                    "paused": not self._bag_pause.is_set(),
                    "rate": self._bag_rate,
                    "index": self._bag_index,
                    "count": len(self._bag_records),
                }
            return {
                "type": "state",
                "mode": self._mode,
                "fleet": self._fleet,
                "selected": selected,
                "robots": robots,
                "jpeg": jpeg_b64,
                "bag": bag,
            }

    def _throttled_jpeg_b64(self, selected: str | None, now: float) -> str | None:
        """Refresh base64 JPEG at ``_jpeg_hz`` for the selected robot."""
        if not selected or selected not in self._jpeg:
            self._jpeg_b64 = None
            self._jpeg_b64_robot = None
            return None
        period = 1.0 / max(1.0, self._jpeg_hz)
        if (
            self._jpeg_b64_robot != selected
            or self._jpeg_b64 is None
            or (now - self._jpeg_b64_t) >= period
        ):
            self._jpeg_b64 = base64.b64encode(self._jpeg[selected]).decode("ascii")
            self._jpeg_b64_robot = selected
            self._jpeg_b64_t = now
        return self._jpeg_b64

    def bag_cmd(self, cmd: str, **kwargs: Any) -> None:
        if self._mode != "bag":
            return
        if cmd == "pause":
            self._bag_pause.clear()
        elif cmd == "play":
            self._bag_pause.set()
            self._bag_wall0 = time.time()
            if self._bag_records and self._bag_index < len(self._bag_records):
                self._bag_t0 = float(self._bag_records[self._bag_index].t)
        elif cmd == "seek":
            self._bag_seek_t = float(kwargs.get("t", 0.0))
        elif cmd == "rate":
            self._bag_rate = max(0.05, float(kwargs.get("rate", 1.0)))

    def start_live(
        self,
        *,
        fleet: str | None = None,
        robot: str | None = None,
        connect: str | None = None,
    ) -> None:
        self._mode = "live"
        self._connect = connect
        self._fleet = fleet
        if not fleet:
            raise ValueError("fleet is required")
        self._start_fleet_live(fleet, connect)

    def _start_fleet_live(self, fleet: str, connect: str | None) -> None:
        from rosie.fleet import Fleet

        f = Fleet(fleet, connect=connect)
        self._fleet_obj = f
        key = f.resolve_key("*/pose")

        def on_pose(sample: zenoh.Sample) -> None:
            try:
                k = str(sample.key_expr)
                raw = sample.payload.to_bytes()
            except Exception:
                return
            rid, rel = _robot_and_rel(k, fleet)
            if not rid or rel != "pose":
                return
            self._ingest_pose(rid, raw)

        self._subs.append(f.session.declare_subscriber(key, on_pose))

        try:
            pkey = f.resolve_key("*/presence")

            def on_pres(sample: zenoh.Sample) -> None:
                try:
                    k = str(sample.key_expr)
                    data = decode_json(sample.payload.to_bytes())
                except Exception:
                    return
                rid, rel = _robot_and_rel(k, fleet)
                if not rid or rel != "presence":
                    return
                with self._lock:
                    if rid not in self._robots:
                        self._robots[rid] = {
                            "x": 0.0,
                            "y": 0.0,
                            "theta": 0.0,
                            "mode": "?",
                            "t": time.time(),
                            "status": data.get("status"),
                        }

            self._subs.append(f.session.declare_subscriber(pkey, on_pres))
        except Exception:
            pass

    def _start_robot_live(
        self, robot: str, connect: str | None, *, fleet: str | None
    ) -> None:
        session = Session(robot=robot, fleet=fleet, connect=connect, name="viz")
        self._session = session
        self._fleet = session.fleet

        def on_pose(msg: dict) -> None:
            self._apply_pose(robot, msg, time.time())

        session.subscribe_json(topics.POSE, on_pose)

    def _ensure_camera_sub(self, robot: str) -> None:
        if self._cam_robot == robot:
            return
        if self._cam_session is not None:
            self._cam_session.close()
            self._cam_session = None
        self._cam_robot = robot

        def on_jpeg(data: bytes) -> None:
            with self._lock:
                self._jpeg[robot] = data

        if self._session is not None and self._session.robot == robot:
            self._session.subscribe_bytes(topics.CAMERA_COMPRESSED, on_jpeg)
            try:
                self._session.publish(
                    topics.CMD,
                    json.dumps({"op": "camera_enable", "value": True}).encode(),
                    qos=Qos.COMMAND,
                )
            except Exception:
                pass
            return

        # Dedicated session for camera under fleet identity
        s = Session(
            robot=robot,
            fleet=self._fleet,
            connect=self._connect,
            name="viz-cam",
        )
        self._cam_session = s
        s.subscribe_bytes(topics.CAMERA_COMPRESSED, on_jpeg)
        try:
            s.publish(
                topics.CMD,
                json.dumps({"op": "camera_enable", "value": True}).encode(),
                qos=Qos.COMMAND,
            )
        except Exception:
            pass

    def _ingest_pose(self, robot: str, raw: bytes) -> None:
        try:
            msg = decode_json(raw)
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        self._apply_pose(robot, msg, time.time())

    def _apply_pose(self, robot: str, msg: dict, t: float) -> None:
        import math

        x = float(msg.get("x", 0.0))
        y = float(msg.get("y", 0.0))
        if "theta" in msg and msg["theta"] is not None:
            theta = float(msg["theta"])
        elif "heading_deg" in msg and msg["heading_deg"] is not None:
            theta = float(msg["heading_deg"]) * math.pi / 180.0
        else:
            theta = 0.0
        entry = {
            "x": x,
            "y": y,
            "theta": theta,
            "heading_deg": msg.get("heading_deg"),
            "mode": msg.get("mode", "?"),
            "dist": msg.get("dist"),
            "navigating": msg.get("navigating"),
            "goal_id": msg.get("goal_id"),
            "t": t,
        }
        with self._lock:
            self._robots[robot] = entry
            trail = self._trails.setdefault(robot, [])
            if not trail or abs(trail[-1][0] - x) > 1e-4 or abs(trail[-1][1] - y) > 1e-4:
                trail.append((x, y))
                if len(trail) > self.trail_max:
                    del trail[: len(trail) - self.trail_max]

    def start_bag(
        self,
        path: str | Path,
        *,
        fleet: str | None = None,
        connect: str | None = None,
        rate: float = 1.0,
        start: float | None = None,
        end: float | None = None,
        key: str | None = None,
    ) -> None:
        from rosie.bag import load_records

        self._mode = "bag"
        self._connect = connect
        bag_path = Path(path).expanduser()
        header, records = load_records(
            bag_path, start=start, end=end, key=key, fleet=fleet
        )
        self._bag_path = str(bag_path)
        self._bag_records = records
        self._bag_index = 0
        self._bag_rate = max(0.05, float(rate))
        self._fleet = fleet or header.get("fleet") or os.environ.get("ROSIE_FLEET")
        self._bag_stop.clear()
        self._bag_pause.set()
        if records:
            self._bag_t0 = float(records[0].t)
            self._bag_wall0 = time.time()
        self._bag_thread = threading.Thread(
            target=self._bag_loop, name="viz-bag", daemon=True
        )
        self._bag_thread.start()

    def _bag_loop(self) -> None:
        records = self._bag_records
        if not records:
            return
        fleet = self._fleet
        while not self._bag_stop.is_set():
            seek = self._bag_seek_t
            if seek is not None:
                self._bag_seek_t = None
                with self._lock:
                    self._robots.clear()
                    self._trails.clear()
                    self._jpeg.clear()
                    self._jpeg_b64 = None
                    self._jpeg_b64_robot = None
                idx = 0
                for i, rec in enumerate(records):
                    if float(rec.t) <= seek:
                        idx = i
                    else:
                        break
                for rec in records[: idx + 1]:
                    self._apply_bag_record(rec, fleet)
                self._bag_index = idx
                self._bag_t0 = float(records[idx].t)
                self._bag_wall0 = time.time()
                continue

            if not self._bag_pause.is_set():
                time.sleep(0.05)
                continue
            if self._bag_index >= len(records):
                self._bag_pause.clear()
                time.sleep(0.05)
                continue
            rec = records[self._bag_index]
            target = self._bag_wall0 + (float(rec.t) - self._bag_t0) / self._bag_rate
            delay = target - time.time()
            if delay > 0.002:
                time.sleep(min(delay, 0.05))
                continue
            self._apply_bag_record(rec, fleet)
            self._bag_index += 1

    def _apply_bag_record(self, rec: Any, fleet: str | None) -> None:
        rid, rel = _robot_and_rel(rec.key, fleet)
        if not rid:
            return
        if rel == "pose" or rel.endswith("pose"):
            self._ingest_pose(rid, rec.payload)
        elif "camera/compressed" in rel:
            with self._lock:
                self._jpeg[rid] = rec.payload
