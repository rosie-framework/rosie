"""Load a user-supplied driver class (BYO escape hatch)."""

from __future__ import annotations

import importlib
from typing import Any


def resolve_byo_class(class_path: str) -> type:
    """Resolve ``module:Class`` or ``module.Class`` without instantiating."""
    class_path = str(class_path).strip()
    if ":" in class_path:
        mod_name, cls_name = class_path.split(":", 1)
    else:
        parts = class_path.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"invalid class path {class_path!r} (use module:Class or module.Class)"
            )
        mod_name, cls_name = parts
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name, None)
    if cls is None:
        raise ValueError(f"class {cls_name!r} not found in module {mod_name!r}")
    return cls


def load_byo(class_path: str, config: dict[str, Any]) -> Any:
    """Instantiate ``module:Class`` or ``module.Class`` with optional ``from_config``."""
    cls = resolve_byo_class(class_path)
    if hasattr(cls, "from_config"):
        return cls.from_config(config)
    return cls(config)
