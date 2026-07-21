"""Fleet manifest — declarative expected team membership for bring-up."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RobotSpec:
    """One expected robot in a fleet manifest."""

    id: str
    kind: str | None = None
    status: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FleetManifest:
    """Composition root for team bring-up (not ROS-style remapped launch).

    Example JSON::

        {
          "fleet": "lab",
          "connect": "tcp/192.168.8.2:7447",
          "defaults": {"v_max": 0.3},
          "robots": [
            {"id": "car1", "kind": "esp32-car", "status": "ready"},
            {"id": "car2", "kind": "esp32-car"}
          ]
        }
    """

    fleet: str
    robots: tuple[RobotSpec, ...]
    connect: str | None = None
    defaults: dict[str, Any] = field(default_factory=dict)

    def robot_ids(self) -> list[str]:
        return [r.id for r in self.robots]

    def required_status(self, robot_id: str) -> str | None:
        for r in self.robots:
            if r.id == robot_id:
                return r.status
        return None


def _normalize_id(value: str, *, label: str) -> str:
    value = str(value).strip().strip("/")
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if "/" in value:
        raise ValueError(f"{label} must not contain '/'")
    return value


def _parse_robot(raw: Any) -> RobotSpec:
    if isinstance(raw, str):
        return RobotSpec(id=_normalize_id(raw, label="robot id"))
    if not isinstance(raw, dict):
        raise ValueError(f"robot entry must be string or object, got {type(raw).__name__}")
    rid = raw.get("id") or raw.get("robot") or raw.get("robot_id")
    if not rid:
        raise ValueError("robot entry missing 'id'")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("robot params must be an object")
    status = raw.get("status")
    kind = raw.get("kind") or raw.get("type")
    return RobotSpec(
        id=_normalize_id(str(rid), label="robot id"),
        kind=str(kind) if kind else None,
        status=str(status) if status else None,
        params=dict(params),
    )


def manifest_from_dict(data: dict[str, Any]) -> FleetManifest:
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    fleet = data.get("fleet") or data.get("fleet_id")
    if not fleet:
        raise ValueError("manifest missing 'fleet'")
    robots_raw = data.get("robots")
    if not isinstance(robots_raw, list) or not robots_raw:
        raise ValueError("manifest 'robots' must be a non-empty list")
    robots = tuple(_parse_robot(r) for r in robots_raw)
    ids = [r.id for r in robots]
    if len(ids) != len(set(ids)):
        raise ValueError("manifest has duplicate robot ids")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("manifest 'defaults' must be an object")
    connect = data.get("connect")
    return FleetManifest(
        fleet=_normalize_id(str(fleet), label="fleet"),
        robots=robots,
        connect=str(connect) if connect else None,
        defaults=dict(defaults),
    )


def _load_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError(
                "PyYAML is required for .yaml/.yml manifests. "
                'Install with: pip install pyyaml  (or use a .json manifest)'
            ) from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"manifest root must be an object ({path})")
    return data


def load_manifest(path: str | Path) -> FleetManifest:
    """Load a fleet manifest from JSON (or YAML if PyYAML is installed)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"manifest not found: {p}")
    return manifest_from_dict(_load_data(p))
