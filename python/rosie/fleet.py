"""Fleet helper — discovery, bring-up wait, and fleet-scoped topic introspection."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import zenoh

from .manifest import FleetManifest
from .messages import decode_json
from .std_msgs import Cmd, LeaderClaim, RobotPresence


def _normalize_fleet(fleet: str) -> str:
    fleet = str(fleet).strip().strip("/")
    if not fleet:
        raise ValueError("fleet must be non-empty")
    if "/" in fleet:
        raise ValueError("fleet must not contain '/'")
    return fleet


@dataclass
class TopicMap:
    """Topics heard under a fleet, grouped by robot (or ``_fleet``)."""

    fleet: str
    by_robot: dict[str, list[str]] = field(default_factory=dict)

    def flat(self) -> list[str]:
        """Full keyexprs, sorted."""
        out: list[str] = []
        for robot, rels in sorted(self.by_robot.items()):
            for rel in rels:
                out.append(f"{self.fleet}/{robot}/{rel}")
        return out


class Fleet:
    """Host-side view of a fleet: presence, wait/bring-up, topics, estop, leader.

    Owns its own Zenoh connection (not a robot Session). Fleet-wide topics
    live under ``{fleet}/_fleet/...``. Robot presence is ``{fleet}/{robot}/presence``.
    """

    def __init__(self, fleet: str, connect: str | None = None):
        self.fleet = _normalize_fleet(fleet)
        self.connect = connect or os.environ.get("ROSIE_CONNECT")

        conf = zenoh.Config()
        if self.connect:
            conf.insert_json5("connect/endpoints", f'["{self.connect}"]')
        self._session = zenoh.open(conf)
        self._subs: list[Any] = []
        self._presence_sub: Any | None = None
        self._lock = threading.Lock()
        self._presence: dict[str, tuple[float, RobotPresence]] = {}
        self._leader: LeaderClaim | None = None
        self._leader_stamp: float = 0.0

    def close(self) -> None:
        for s in self._subs:
            try:
                s.undeclare()
            except Exception:
                pass
        self._subs.clear()
        self._session.close()

    def __enter__(self) -> Fleet:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def session(self) -> zenoh.Session:
        """Underlying Zenoh session (for advanced tooling)."""
        return self._session

    def fleet_key(self, rel: str) -> str:
        rel = str(rel).strip().lstrip("/")
        return f"{self.fleet}/_fleet/{rel}"

    def resolve_key(self, key: str) -> str:
        """Resolve a key relative to this fleet (or pass through absolute paths).

        - ``\"pose\"`` → not valid alone (needs robot); use ``\"car1/pose\"``
        - ``\"car1/pose\"`` / ``\"*/pose\"`` / ``\"_fleet/estop\"`` → ``{fleet}/...``
        - ``\"/global/x\"`` or key already starting with ``{fleet}/`` → as-is (strip leading /)
        """
        key = str(key).strip()
        if not key:
            raise ValueError("key must be non-empty")
        if key.startswith("/"):
            return key.lstrip("/")
        if key == "**" or key.startswith(f"{self.fleet}/"):
            return key if key != "**" else f"{self.fleet}/**"
        return f"{self.fleet}/{key.lstrip('/')}"

    def _parse_presence(self, raw: bytes) -> RobotPresence | None:
        try:
            return RobotPresence.from_bytes(raw)
        except Exception:
            try:
                data = decode_json(raw)
                return RobotPresence(
                    stamp=float(data.get("stamp") or 0.0),
                    robot_id=str(data.get("robot_id") or ""),
                    fleet_id=data.get("fleet_id"),
                    status=str(data.get("status") or ""),
                )
            except Exception:
                return None

    def _on_presence(self, sample: zenoh.Sample) -> None:
        msg = self._parse_presence(sample.payload.to_bytes())
        if msg is None or not msg.robot_id:
            return
        with self._lock:
            self._presence[msg.robot_id] = (time.time(), msg)

    def _ensure_presence_sub(self) -> None:
        if self._presence_sub is not None:
            return
        key = f"{self.fleet}/*/presence"
        self._presence_sub = self._session.declare_subscriber(key, self._on_presence)
        self._subs.append(self._presence_sub)

    def robots(self, ttl_s: float = 3.0, wait_s: float = 0.5) -> list[RobotPresence]:
        """Return robots with presence fresher than ``ttl_s`` seconds."""
        self._ensure_presence_sub()
        time.sleep(max(0.0, wait_s))
        now = time.time()
        out: list[RobotPresence] = []
        with self._lock:
            stale = [rid for rid, (ts, _) in self._presence.items() if now - ts > ttl_s]
            for rid in stale:
                del self._presence[rid]
            out = [msg for _, msg in sorted(self._presence.values(), key=lambda x: x[1].robot_id)]
        return out

    def wait(
        self,
        robots: Sequence[str] | FleetManifest,
        *,
        timeout_s: float = 30.0,
        ttl_s: float = 3.0,
        status: str | None = None,
        poll_s: float = 0.5,
    ) -> list[RobotPresence]:
        """Block until expected robots are present (team bring-up gate).

        ``robots`` is either a list of ids or a :class:`FleetManifest`.
        When a manifest entry (or ``status=``) specifies a required status,
        that robot must advertise matching ``RobotPresence.status``.

        Raises ``TimeoutError`` if the team is not ready before ``timeout_s``.
        """
        if isinstance(robots, FleetManifest):
            if robots.fleet != self.fleet:
                raise ValueError(
                    f"manifest fleet {robots.fleet!r} != Fleet fleet {self.fleet!r}"
                )
            expected = list(robots.robots)
            status_for = {r.id: (r.status or status) for r in expected}
            want_ids = [r.id for r in expected]
        else:
            want_ids = []
            for r in robots:
                rid = str(r).strip().strip("/")
                if not rid:
                    raise ValueError("robot id must be non-empty")
                if "/" in rid:
                    raise ValueError(f"robot id must not contain '/': {rid!r}")
                want_ids.append(rid)
            if not want_ids:
                raise ValueError("robots must be non-empty")
            status_for = {rid: status for rid in want_ids}

        self._ensure_presence_sub()
        deadline = time.monotonic() + max(0.0, timeout_s)
        last_missing: list[str] = list(want_ids)

        while True:
            now = time.time()
            with self._lock:
                stale = [rid for rid, (ts, _) in self._presence.items() if now - ts > ttl_s]
                for rid in stale:
                    del self._presence[rid]
                present = dict(self._presence)

            missing: list[str] = []
            ready: list[RobotPresence] = []
            for rid in want_ids:
                entry = present.get(rid)
                if entry is None:
                    missing.append(rid)
                    continue
                _, msg = entry
                need = status_for.get(rid)
                if need and msg.status != need:
                    missing.append(f"{rid}(want status={need!r} got={msg.status!r})")
                    continue
                ready.append(msg)

            if not missing:
                return sorted(ready, key=lambda m: m.robot_id)

            last_missing = missing
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"fleet {self.fleet!r}: timed out waiting for robots; "
                    f"still missing: {', '.join(last_missing)}"
                )
            time.sleep(max(0.05, poll_s))

    def topics(
        self,
        *,
        selector: str | None = None,
        wait_s: float = 2.0,
    ) -> TopicMap:
        """Passively discover keys under the fleet (listen for ``wait_s`` seconds).

        Default selector is ``{fleet}/**``. Returns topics grouped by robot id
        (relative names under each robot, or under ``_fleet``).
        """
        key = self.resolve_key(selector or "**")
        seen: set[str] = set()
        lock = threading.Lock()

        def _on(sample: zenoh.Sample) -> None:
            try:
                k = str(sample.key_expr)
            except Exception:
                return
            with lock:
                seen.add(k)

        sub = self._session.declare_subscriber(key, _on)
        try:
            time.sleep(max(0.0, wait_s))
        finally:
            try:
                sub.undeclare()
            except Exception:
                pass

        by_robot: dict[str, set[str]] = {}
        prefix = f"{self.fleet}/"
        with lock:
            keys = sorted(seen)
        for k in keys:
            if not k.startswith(prefix):
                # Still attribute under a synthetic bucket if selector was absolute
                by_robot.setdefault("_other", set()).add(k)
                continue
            rest = k[len(prefix) :]
            parts = rest.split("/", 1)
            if len(parts) == 1:
                robot, rel = parts[0], ""
            else:
                robot, rel = parts[0], parts[1]
            by_robot.setdefault(robot, set()).add(rel)

        return TopicMap(
            fleet=self.fleet,
            by_robot={rid: sorted(rels) for rid, rels in sorted(by_robot.items())},
        )

    def publish_estop(self) -> None:
        """Broadcast fleet emergency stop on ``{fleet}/_fleet/estop``."""
        key = self.fleet_key("estop")
        msg = Cmd(op="estop")
        self._session.put(key, msg.to_bytes())

    def claim_leader(self, robot_id: str, term: int = 1) -> LeaderClaim:
        """Publish a leader claim on ``{fleet}/_fleet/coord/leader``."""
        robot_id = str(robot_id).strip().strip("/")
        if not robot_id:
            raise ValueError("robot_id must be non-empty")
        claim = LeaderClaim(robot_id=robot_id, term=int(term))
        key = self.fleet_key("coord/leader")
        self._session.put(key, claim.to_bytes())
        with self._lock:
            self._leader = claim
            self._leader_stamp = time.time()
        return claim

    def _on_leader(self, sample: zenoh.Sample) -> None:
        raw = sample.payload.to_bytes()
        try:
            claim = LeaderClaim.from_bytes(raw)
        except Exception:
            try:
                data = decode_json(raw)
                claim = LeaderClaim(
                    stamp=float(data.get("stamp") or 0.0),
                    robot_id=str(data.get("robot_id") or ""),
                    term=int(data.get("term") or 0),
                )
            except Exception:
                return
        with self._lock:
            if self._leader is None or claim.term >= self._leader.term:
                self._leader = claim
                self._leader_stamp = time.time()

    def get_leader(self, wait_s: float = 0.5) -> LeaderClaim | None:
        """Return the latest known leader claim (subscribes on first call)."""
        if not hasattr(self, "_leader_sub"):
            key = self.fleet_key("coord/leader")
            self._leader_sub = self._session.declare_subscriber(key, self._on_leader)
            self._subs.append(self._leader_sub)
        time.sleep(max(0.0, wait_s))
        with self._lock:
            return self._leader
