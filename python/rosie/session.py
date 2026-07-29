"""Rosie Session — Zenoh session bound to a robot (+ optional fleet)."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

import zenoh

from .messages import decode_json, encode_json, stamp_now, with_stamp

_RESERVED_ROBOT = "_fleet"


class Qos(Enum):
    """Delivery class for publications (see docs/conventions.md).

    Host uses BLOCK for COMMAND/CRITICAL so one-shots are not dropped under
    congestion. MCU publishers use DROP + high priority instead (see firmware).
    """

    STREAM = "stream"
    COMMAND = "command"
    CRITICAL = "critical"
    BULK = "bulk"


# Host-side put kwargs. COMMAND/CRITICAL block; STREAM/BULK may drop.
_QOS_KWARGS: dict[Qos, dict[str, Any]] = {
    Qos.STREAM: {
        "congestion_control": zenoh.CongestionControl.DROP,
        "priority": zenoh.Priority.DATA,
        "express": False,
    },
    Qos.COMMAND: {
        "congestion_control": zenoh.CongestionControl.BLOCK,
        "priority": zenoh.Priority.INTERACTIVE_HIGH,
        "express": True,
    },
    Qos.CRITICAL: {
        "congestion_control": zenoh.CongestionControl.BLOCK,
        "priority": zenoh.Priority.REAL_TIME,
        "express": True,
    },
    Qos.BULK: {
        "congestion_control": zenoh.CongestionControl.DROP,
        "priority": zenoh.Priority.DATA_LOW,
        "express": False,
    },
}


def qos_put_kwargs(qos: Qos = Qos.STREAM) -> dict[str, Any]:
    """Resolved ``Session.put`` kwargs for a delivery class (for tests / raw puts)."""
    return dict(_QOS_KWARGS[qos])

# Host sessions default to the local router. MCU / remote robots still need an
# explicit LAN locator in robot.yaml (or ROSIE_CONNECT when the host is remote).
DEFAULT_CONNECT = "tcp/127.0.0.1:7447"


def resolve_connect(connect: str | None = None) -> str:
    """constructor arg → ROSIE_CONNECT → local router default."""
    return connect or os.environ.get("ROSIE_CONNECT") or DEFAULT_CONNECT


def _open_zenoh(
    connect: str,
    *,
    user: str | None = None,
    password: str | None = None,
    fleet: str | None = None,
    secure: bool = False,
) -> Any:
    """Open a Zenoh session.

    Usrpwd is applied when ``password`` / ``user`` are given explicitly, or when
    ``secure=True`` and a host secret resolves. Open mode (default) never reads
    leftover secret files.
    """
    from .auth import (
        BusCredentials,
        apply_usrpwd_to_zenoh_config,
        credentials_for,
        resolve_secret_plaintext,
    )

    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", f'["{connect}"]')
    if user and password:
        creds = BusCredentials(user=user, password=password)
    elif password is not None:
        creds = credentials_for(fleet=fleet, password=password)
    elif secure:
        pwd = resolve_secret_plaintext(fleet=fleet, secure=True)
        creds = credentials_for(fleet=fleet, password=pwd)
    else:
        creds = None
    if creds is not None:
        apply_usrpwd_to_zenoh_config(conf, creds)
    return zenoh.open(conf)


def _normalize_id(value: str, *, label: str) -> str:
    value = str(value).strip().strip("/")
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if "/" in value:
        raise ValueError(f"{label} must not contain '/'")
    return value


def _normalize_robot(robot: str) -> str:
    robot = _normalize_id(robot, label="robot")
    if robot == _RESERVED_ROBOT:
        raise ValueError(f"robot id '{_RESERVED_ROBOT}' is reserved")
    return robot


def _normalize_fleet(fleet: str | None) -> str | None:
    if fleet is None:
        return None
    fleet = str(fleet).strip().strip("/")
    if not fleet:
        return None
    return _normalize_id(fleet, label="fleet")


class Session:
    """Open a Zenoh session and publish/subscribe JSON or raw bytes.

    Identity:
      - ``robot`` (required): topic boundary
      - ``fleet`` (optional): when set, robot topics are ``{fleet}/{robot}/...``

    Resolution order for connect / robot / fleet:
      constructor arg → env (ROSIE_CONNECT / ROSIE_ROBOT / ROSIE_FLEET) → defaults
      (connect defaults to ``tcp/127.0.0.1:7447`` — local ``rosie router``)
    """

    def __init__(
        self,
        robot: str | None = None,
        fleet: str | None = None,
        connect: str | None = None,
        name: str | None = None,
        *,
        user: str | None = None,
        password: str | None = None,
        secure: bool = False,
    ):
        self.name = name or "session"
        self.robot = _normalize_robot(
            robot or os.environ.get("ROSIE_ROBOT") or "robot"
        )
        env_fleet = os.environ.get("ROSIE_FLEET")
        self.fleet = _normalize_fleet(
            fleet if fleet is not None else env_fleet
        )
        self.connect = resolve_connect(connect)
        self.session = _open_zenoh(
            self.connect,
            user=user,
            password=password,
            fleet=self.fleet,
            secure=secure,
        )

        self._subs: list[Any] = []
        self._timers: list[_Timer] = []
        self._params: dict[str, Any] = {}
        self._spinning = False

    def close(self) -> None:
        for t in self._timers:
            t.cancel()
        for s in self._subs:
            try:
                s.undeclare()
            except Exception:
                pass
        self.session.close()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- parameters (local / env; no parameter server) ---------------

    def declare_parameter(self, name: str, default: Any = None) -> Any:
        env_key = f"ROSIE_PARAM_{name.upper()}"
        if env_key in os.environ:
            val: Any = os.environ[env_key]
            self._params[name] = val
            return val
        self._params[name] = default
        return default

    def get_parameter(self, name: str, default: Any = None) -> Any:
        return self._params.get(name, default)

    # --- topic names -------------------------------------------------

    def _robot_prefix(self) -> str:
        if self.fleet:
            return f"{self.fleet}/{self.robot}"
        return self.robot

    def resolve_name(self, name: str) -> str:
        """Resolve a topic name to a Zenoh keyexpr.

        - Relative (``\"cmd_vel\"``) → ``\"{robot}/cmd_vel\"`` or
          ``\"{fleet}/{robot}/cmd_vel\"``
        - Absolute (``\"/global/estop\"``) → ``\"global/estop\"``
        """
        if not name or not str(name).strip():
            raise ValueError("topic name must be non-empty")
        name = str(name).strip()
        if name.startswith("/"):
            return name.lstrip("/")
        return f"{self._robot_prefix()}/{name.lstrip('/')}"

    def resolve_fleet_name(self, name: str) -> str:
        """Resolve a fleet-scoped topic: ``{fleet}/_fleet/{name}``."""
        if not self.fleet:
            raise ValueError("fleet is required for fleet-scoped topics")
        if not name or not str(name).strip():
            raise ValueError("topic name must be non-empty")
        name = str(name).strip().lstrip("/")
        return f"{self.fleet}/_fleet/{name}"

    # --- publish / subscribe ----------------------------------------

    def publish(
        self,
        key: str,
        payload: bytes | dict[str, Any],
        *,
        qos: Qos = Qos.STREAM,
    ) -> None:
        """Publish raw bytes, or a dict (JSON with auto stamp if missing).

        ``key`` is a relative or absolute topic name (see ``resolve_name``).
        ``qos`` selects delivery class (default STREAM).
        """
        key = self.resolve_name(key)
        if isinstance(payload, dict):
            payload = encode_json(with_stamp(payload))
        self.session.put(key, payload, **qos_put_kwargs(qos))

    def publish_msg(
        self, key: str, msg: Any, *, qos: Qos = Qos.STREAM
    ) -> None:
        """Publish a generated std_msgs dataclass (sets stamp when missing)."""
        key = self.resolve_name(key)
        if hasattr(msg, "stamp") and not msg.stamp:
            msg.stamp = stamp_now()
        raw = msg.to_bytes() if hasattr(msg, "to_bytes") else encode_json(msg)
        self.session.put(key, raw, **qos_put_kwargs(qos))

    def publish_fleet(
        self,
        key: str,
        payload: bytes | dict[str, Any],
        *,
        qos: Qos = Qos.STREAM,
    ) -> None:
        """Publish on a fleet-scoped topic (requires ``fleet``)."""
        key = self.resolve_fleet_name(key)
        if isinstance(payload, dict):
            payload = encode_json(with_stamp(payload))
        self.session.put(key, payload, **qos_put_kwargs(qos))

    def create_subscription(
        self,
        key: str,
        callback: Callable[[Any], None],
        msg_type: type | None = None,
    ) -> None:
        """Subscribe; callback gets msg_type instance or dict (JSON) or bytes."""
        key = self.resolve_name(key)

        def _cb(sample: zenoh.Sample) -> None:
            raw = sample.payload.to_bytes()
            try:
                if msg_type is bytes:
                    callback(raw)
                elif msg_type is not None and hasattr(msg_type, "from_bytes"):
                    callback(msg_type.from_bytes(raw))
                else:
                    try:
                        callback(decode_json(raw))
                    except Exception:
                        callback(raw)
            except Exception as e:
                print(f"  [{self.name}] warn: bad payload on {key}: {e}")

        self._subs.append(self.session.declare_subscriber(key, _cb))

    def create_fleet_subscription(
        self,
        key: str,
        callback: Callable[[Any], None],
        msg_type: type | None = None,
    ) -> None:
        """Subscribe to a fleet-scoped topic (requires ``fleet``)."""
        key = self.resolve_fleet_name(key)

        def _cb(sample: zenoh.Sample) -> None:
            raw = sample.payload.to_bytes()
            try:
                if msg_type is bytes:
                    callback(raw)
                elif msg_type is not None and hasattr(msg_type, "from_bytes"):
                    callback(msg_type.from_bytes(raw))
                else:
                    try:
                        callback(decode_json(raw))
                    except Exception:
                        callback(raw)
            except Exception as e:
                print(f"  [{self.name}] warn: bad payload on {key}: {e}")

        self._subs.append(self.session.declare_subscriber(key, _cb))

    def subscribe_bytes(self, key: str, handler: Callable[[bytes], None]) -> None:
        self.create_subscription(key, handler, msg_type=bytes)

    def subscribe_json(self, key: str, handler: Callable[[dict], None]) -> None:
        self.create_subscription(key, handler, msg_type=None)

    # --- timers + spin ----------------------------------------------

    def create_timer(self, period_s: float, callback: Callable[[], None]) -> None:
        t = _Timer(period_s, callback)
        self._timers.append(t)
        t.start()

    def spin(self) -> None:
        """Block until KeyboardInterrupt; timers already run on threads."""
        self._spinning = True
        try:
            while self._spinning:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self._spinning = False

    def spin_once(self, timeout_s: float = 0.1) -> None:
        time.sleep(timeout_s)


class _Timer:
    def __init__(self, period_s: float, callback: Callable[[], None]):
        self.period_s = period_s
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        def _run() -> None:
            while not self._stop.wait(self.period_s):
                try:
                    self.callback()
                except Exception as e:
                    print(f"  timer error: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()
