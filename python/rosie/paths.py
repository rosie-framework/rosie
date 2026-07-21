"""Locate Rosie install artifacts (firmware library, home cache)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .bootstrap import rosie_home


def firmware_dir() -> Path:
    """Return the PlatformIO library directory (contains ``library.json``).

    Resolution order:
      1. ``ROSIE_FIRMWARE`` env override
      2. Packaged ``rosie/pio_libs/rosie`` (wheel / copied tree)
      3. Editable checkout: ``<repo>/firmware`` next to ``python/``
    """
    override = os.environ.get("ROSIE_FIRMWARE")
    if override:
        p = Path(override).expanduser().resolve()
        if not (p / "library.json").is_file():
            raise FileNotFoundError(
                f"ROSIE_FIRMWARE={override!r} has no library.json"
            )
        return p

    pkg = Path(__file__).resolve().parent
    packaged = pkg / "pio_libs" / "rosie"
    if (packaged / "library.json").is_file():
        return packaged.resolve()

    # Editable checkout: python/rosie → python → repo; firmware lives at repo/firmware
    repo_fw = pkg.parents[1] / "firmware"
    if (repo_fw / "library.json").is_file():
        return repo_fw.resolve()

    raise FileNotFoundError(
        "Could not find Rosie firmware library (library.json).\n"
        "  Install from a Rosie checkout: pip install -e \"/path/to/rosie/python[mcu]\"\n"
        "  Or set ROSIE_FIRMWARE=/path/to/rosie/firmware"
    )


def pio_libs_dir() -> Path:
    """Cache dir for PlatformIO ``lib_extra_dirs`` (contains a ``rosie`` library)."""
    return rosie_home() / "pio_libs"


def ensure_pio_libs_link() -> Path:
    """Ensure ``~/.rosie/pio_libs/rosie`` points at the firmware library.

    Returns the ``pio_libs`` parent suitable for ``PLATFORMIO_LIB_EXTRA_DIRS``.
    """
    fw = firmware_dir()
    root = pio_libs_dir()
    root.mkdir(parents=True, exist_ok=True)
    link = root / "rosie"
    _ensure_link(link, fw)
    return root


def ensure_project_lib_link(project_dir: Path) -> Path:
    """Ensure ``<project>/lib/rosie`` → firmware library. Returns the link path."""
    fw = firmware_dir()
    lib_dir = Path(project_dir).expanduser().resolve() / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    link = lib_dir / "rosie"
    _ensure_link(link, fw)
    return link


def _ensure_link(link: Path, target: Path) -> None:
    target = target.resolve()
    if link.is_symlink():
        try:
            if link.resolve() == target:
                return
        except OSError:
            pass
        link.unlink()
    elif link.exists():
        # Real directory/file — do not clobber a vendored copy
        if link.is_dir() and (link / "library.json").is_file():
            return
        raise FileExistsError(
            f"{link} exists and is not a symlink to the Rosie firmware library; "
            "remove it or set ROSIE_FIRMWARE and re-run."
        )
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        # Windows without symlink privilege — copy tree once
        if link.exists():
            shutil.rmtree(link)
        shutil.copytree(target, link)
