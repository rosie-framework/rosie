"""Fetch and cache a pinned zenohd binary for the host platform."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Pin to match a known-good eclipse-zenoh client series.
ZENOHD_VERSION = "1.9.0"

_BASE = f"https://download.eclipse.org/zenoh/zenoh/{ZENOHD_VERSION}"

# (download URL relative filename, sha256 of the zip)
_ARTIFACTS: dict[str, tuple[str, str]] = {
    "aarch64-apple-darwin": (
        f"zenoh-{ZENOHD_VERSION}-aarch64-apple-darwin-standalone.zip",
        "13845799d1ab24f6aed209612e01346874b0857eda37b8d45b5b8b4897b52064",
    ),
    "x86_64-apple-darwin": (
        f"zenoh-{ZENOHD_VERSION}-x86_64-apple-darwin-standalone.zip",
        "54226409c16392364f6cf12ba62fbe2b9e22d630e17f39df98f2a8e8e06d783b",
    ),
    "aarch64-unknown-linux-gnu": (
        f"zenoh-{ZENOHD_VERSION}-aarch64-unknown-linux-gnu-standalone.zip",
        "34e24153dcf69e18f407eb1d2921226a273960cfaa03cefceb452d16434341e7",
    ),
    "x86_64-unknown-linux-gnu": (
        f"zenoh-{ZENOHD_VERSION}-x86_64-unknown-linux-gnu-standalone.zip",
        "f18081184b089e79e605f2c0cb3f7790fbf101ae94942988f716e19e1810a46e",
    ),
}


def rosie_home() -> Path:
    return Path(os.environ.get("ROSIE_HOME", Path.home() / ".rosie"))


def zenohd_cache_path() -> Path:
    return rosie_home() / "bin" / "zenohd"


def detect_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        raise RuntimeError(
            f"Unsupported CPU architecture for bundled zenohd: {machine!r}. "
            "Install zenohd yourself and put it on PATH, or set ROSIE_ZENOHD."
        )

    if system == "Darwin":
        return f"{arch}-apple-darwin"
    if system == "Linux":
        return f"{arch}-unknown-linux-gnu"
    raise RuntimeError(
        f"Unsupported OS for bundled zenohd: {system!r}. "
        "Windows is not supported yet; install zenohd manually or use a Linux/macOS host."
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zenohd(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.rstrip("/").endswith("zenohd")]
        if not names:
            # Some archives nest under a folder; match basename only.
            names = [n for n in zf.namelist() if Path(n).name == "zenohd"]
        if not names:
            raise RuntimeError(f"zenohd binary not found inside {zip_path.name}")
        # Prefer shortest path (top-level zenohd).
        names.sort(key=lambda n: (n.count("/"), len(n)))
        member = names[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def download_zenohd(*, force: bool = False, quiet: bool = False) -> Path:
    """Download and cache zenohd for this host. Returns path to the binary."""
    dest = zenohd_cache_path()
    if dest.is_file() and not force:
        return dest

    triple = detect_triple()
    if triple not in _ARTIFACTS:
        raise RuntimeError(f"No zenohd artifact mapped for triple {triple!r}")

    filename, expected_sha = _ARTIFACTS[triple]
    url = f"{_BASE}/{filename}"
    if not quiet:
        print(f"Downloading zenohd {ZENOHD_VERSION} ({triple})…")
        print(f"  {url}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rosie-zenohd-") as tmp:
        zip_path = Path(tmp) / filename
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to download zenohd from {url}. "
                "Check your network (SoftAP usually has no internet — run `rosie setup` first). "
                f"Detail: {e}"
            ) from e

        actual = _sha256_file(zip_path)
        if actual != expected_sha:
            raise RuntimeError(
                f"Checksum mismatch for {filename}:\n"
                f"  expected {expected_sha}\n"
                f"  got      {actual}"
            )

        tmp_bin = Path(tmp) / "zenohd"
        _extract_zenohd(zip_path, tmp_bin)
        # Atomic-ish replace
        if dest.exists():
            dest.unlink()
        shutil.move(str(tmp_bin), str(dest))

    if not quiet:
        print(f"Installed zenohd → {dest}")
    return dest


def find_zenohd(*, fetch: bool = True, force: bool = False, quiet: bool = False) -> Path:
    """Resolve zenohd: ROSIE_ZENOHD, PATH, cache, or download."""
    override = os.environ.get("ROSIE_ZENOHD")
    if override:
        p = Path(override).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"ROSIE_ZENOHD={override!r} is not a file")
        return p

    which = shutil.which("zenohd")
    if which:
        return Path(which)

    cached = zenohd_cache_path()
    if cached.is_file() and not force:
        return cached

    if not fetch:
        raise FileNotFoundError(
            "zenohd not found. Run `rosie setup` while online, or install zenohd on PATH."
        )
    return download_zenohd(force=force, quiet=quiet)


def zenohd_version_string(path: Path | None = None) -> str | None:
    """Best-effort version line from `zenohd --version`."""
    import re
    import subprocess

    bin_path = path
    if bin_path is None:
        try:
            bin_path = find_zenohd(fetch=False)
        except FileNotFoundError:
            return None
    try:
        out = subprocess.run(
            [str(bin_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
        if not text:
            return None
        m = re.search(r"zenohd\s+v[\d.]+(?:\s+built with.+)?", text)
        if m:
            return m.group(0).strip()
        return text.splitlines()[-1].strip()
    except Exception:
        return None
