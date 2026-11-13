"""JSON messages that have no ROS equivalent.

Robot data (pose, velocity, images, goals) is CDR on the ROS topics.
These types are the fleet plane: who is here, who leads, and estop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .messages import decode_json, encode_json, stamp_now


@dataclass
class Cmd:
    stamp: float = 0.0
    op: str = ""
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"stamp": float(self.stamp), "op": self.op}
        if self.value is not None:
            body["value"] = self.value
        return body

    def to_bytes(self) -> bytes:
        if self.stamp == 0.0:
            self.stamp = stamp_now()
        return encode_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cmd:
        return cls(
            stamp=float(data.get("stamp", 0.0)),
            op=str(data.get("op", "")),
            value=data.get("value"),
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> Cmd:
        return cls.from_dict(decode_json(raw))


@dataclass
class RobotPresence:
    stamp: float = 0.0
    robot_id: str = ""
    fleet_id: str | None = None
    status: str = ""
    profile: str | None = None
    estop: bool = False

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "stamp": float(self.stamp),
            "robot_id": self.robot_id,
            "status": self.status,
            "estop": bool(self.estop),
        }
        if self.fleet_id is not None:
            body["fleet_id"] = self.fleet_id
        if self.profile is not None:
            body["profile"] = self.profile
        return body

    def to_bytes(self) -> bytes:
        if self.stamp == 0.0:
            self.stamp = stamp_now()
        return encode_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobotPresence:
        return cls(
            stamp=float(data.get("stamp", 0.0)),
            robot_id=str(data.get("robot_id", "")),
            fleet_id=data.get("fleet_id"),
            status=str(data.get("status", "")),
            profile=data.get("profile"),
            estop=bool(data.get("estop", False)),
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> RobotPresence:
        return cls.from_dict(decode_json(raw))


@dataclass
class LeaderClaim:
    stamp: float = 0.0
    robot_id: str = ""
    term: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stamp": float(self.stamp),
            "robot_id": self.robot_id,
            "term": int(self.term),
        }

    def to_bytes(self) -> bytes:
        if self.stamp == 0.0:
            self.stamp = stamp_now()
        return encode_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeaderClaim:
        return cls(
            stamp=float(data.get("stamp", 0.0)),
            robot_id=str(data.get("robot_id", "")),
            term=int(data.get("term", 0)),
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> LeaderClaim:
        return cls.from_dict(decode_json(raw))
