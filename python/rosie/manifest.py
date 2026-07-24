"""Fleet manifest — declarative expected team membership for bring-up."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .fleet_home import default_manifest_path


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
    secret_file: str | None = None
    path: Path | None = None

    def robot_ids(self) -> list[str]:
        return [r.id for r in self.robots]

    def allowed_ids(self) -> set[str]:
        return set(self.robot_ids())

    def required_status(self, robot_id: str) -> str | None:
        for r in self.robots:
            if r.id == robot_id:
                return r.status
        return None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"fleet": self.fleet, "robots": []}
        if self.connect:
            out["connect"] = self.connect
        if self.secret_file:
            out["secret_file"] = self.secret_file
        if self.defaults:
            out["defaults"] = dict(self.defaults)
        robots: list[Any] = []
        for r in self.robots:
            if not r.kind and not r.status and not r.params:
                robots.append(r.id)
            else:
                entry: dict[str, Any] = {"id": r.id}
                if r.kind:
                    entry["kind"] = r.kind
                if r.status:
                    entry["status"] = r.status
                if r.params:
                    entry["params"] = dict(r.params)
                robots.append(entry)
        out["robots"] = robots
        return out


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


def manifest_from_dict(
    data: dict[str, Any],
    *,
    allow_empty_robots: bool = False,
    path: Path | None = None,
) -> FleetManifest:
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    fleet = data.get("fleet") or data.get("fleet_id")
    if not fleet:
        raise ValueError("manifest missing 'fleet'")
    robots_raw = data.get("robots")
    if robots_raw is None:
        robots_raw = []
    if not isinstance(robots_raw, list):
        raise ValueError("manifest 'robots' must be a list")
    if not robots_raw and not allow_empty_robots:
        raise ValueError("manifest 'robots' must be a non-empty list")
    robots = tuple(_parse_robot(r) for r in robots_raw)
    ids = [r.id for r in robots]
    if len(ids) != len(set(ids)):
        raise ValueError("manifest has duplicate robot ids")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("manifest 'defaults' must be an object")
    connect = data.get("connect")
    secret_file = data.get("secret_file")
    return FleetManifest(
        fleet=_normalize_id(str(fleet), label="fleet"),
        robots=robots,
        connect=str(connect) if connect else None,
        defaults=dict(defaults),
        secret_file=str(secret_file) if secret_file else None,
        path=path,
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


def load_manifest(
    path: str | Path,
    *,
    allow_empty_robots: bool = False,
) -> FleetManifest:
    """Load a fleet manifest from JSON (or YAML if PyYAML is installed)."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"manifest not found: {p}")
    return manifest_from_dict(
        _load_data(p),
        allow_empty_robots=allow_empty_robots,
        path=p,
    )


def save_manifest(manifest: FleetManifest, path: str | Path | None = None) -> Path:
    """Write manifest as YAML (preferred) or JSON based on suffix."""
    p = Path(path or manifest.path or default_manifest_path(manifest.fleet))
    p = p.expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = manifest.to_dict()
    suffix = p.suffix.lower()
    if suffix in {".json"}:
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError(
                "PyYAML is required to write .yaml manifests. "
                "Install with: pip install pyyaml"
            ) from e
        if p.suffix.lower() not in {".yaml", ".yml"}:
            p = p.with_suffix(".yaml")
        p.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    return p


def add_robot(
    manifest: FleetManifest,
    robot: RobotSpec | str,
) -> FleetManifest:
    spec = robot if isinstance(robot, RobotSpec) else RobotSpec(id=_normalize_id(robot, label="robot id"))
    if spec.id in manifest.allowed_ids():
        raise ValueError(f"robot {spec.id!r} already in fleet {manifest.fleet!r}")
    return replace(manifest, robots=manifest.robots + (spec,))


def remove_robot(manifest: FleetManifest, robot_id: str) -> FleetManifest:
    rid = _normalize_id(robot_id, label="robot id")
    kept = tuple(r for r in manifest.robots if r.id != rid)
    if len(kept) == len(manifest.robots):
        raise ValueError(f"robot {rid!r} not in fleet {manifest.fleet!r}")
    return replace(manifest, robots=kept)


def resolve_manifest_path(
    *,
    manifest: str | Path | None = None,
    fleet: str | None = None,
) -> Path | None:
    """Resolve manifest path without requiring the file to exist.

    Order: ``--manifest`` → ``ROSIE_FLEET_MANIFEST`` → ``./fleet.yaml`` if present
    → ``~/.rosie/fleets/<fleet>/manifest.yaml`` when fleet is known.
    """
    if manifest is not None:
        return Path(manifest).expanduser().resolve()
    env = os.environ.get("ROSIE_FLEET_MANIFEST")
    if env and env.strip():
        return Path(env.strip()).expanduser().resolve()
    cwd_fleet = Path.cwd() / "fleet.yaml"
    if cwd_fleet.is_file():
        return cwd_fleet.resolve()
    cwd_fleet_yml = Path.cwd() / "fleet.yml"
    if cwd_fleet_yml.is_file():
        return cwd_fleet_yml.resolve()
    if fleet:
        return default_manifest_path(fleet).resolve()
    env_fleet = os.environ.get("ROSIE_FLEET")
    if env_fleet and env_fleet.strip():
        return default_manifest_path(env_fleet.strip()).resolve()
    return None


def resolve_manifest(
    *,
    manifest: str | Path | None = None,
    fleet: str | None = None,
    allow_empty_robots: bool = True,
    required: bool = False,
) -> FleetManifest | None:
    """Load a manifest if a path resolves and the file exists."""
    path = resolve_manifest_path(manifest=manifest, fleet=fleet)
    if path is None:
        if required:
            raise FileNotFoundError(
                "no fleet manifest found (pass --manifest, set ROSIE_FLEET_MANIFEST, "
                "or use --fleet after `rosie fleet init`)"
            )
        return None
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"manifest not found: {path}")
        return None
    return load_manifest(path, allow_empty_robots=allow_empty_robots)
