"""Fleet-verified router discovery for ``connect: auto`` (Linux)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import topics
from .messages import decode_json
from .connect import is_auto_connect


ScoutFn = Callable[[], list["ScoutedRouter"]]
VerifyFn = Callable[[str, str], dict[str, Any] | None]
OpenFn = Callable[[str], Any]


@dataclass
class ScoutedRouter:
    """One scout Hello, reduced to what Rosie needs."""

    zid: str = ""
    whatami: str = ""
    locators: list[str] = field(default_factory=list)


def split_connect_list(connect: str | None) -> list[str]:
    """Split a comma-separated locator list; drop blanks and ``auto``."""
    if connect is None:
        return []
    out: list[str] = []
    for part in str(connect).split(","):
        item = part.strip()
        if not item or is_auto_connect(item):
            continue
        if item not in out:
            out.append(item)
    return out


def _hello_locators(hello: Any) -> list[str]:
    raw = getattr(hello, "locators", None)
    if raw is None:
        return []
    out: list[str] = []
    for loc in raw:
        text = str(loc)
        if text and text not in out:
            out.append(text)
    return out


def scout_routers(*, timeout_s: float = 1.0, scout_fn: ScoutFn | None = None) -> list[ScoutedRouter]:
    """Enumerate Zenoh routers on the LAN. Empty if scouting is unavailable."""
    if scout_fn is not None:
        return scout_fn()
    try:
        import zenoh
    except ImportError:
        return []
    if not hasattr(zenoh, "scout"):
        return []
    found: dict[str, ScoutedRouter] = {}
    try:
        scout = zenoh.scout(what="router", timeout=timeout_s)
    except TypeError:
        try:
            scout = zenoh.scout(what="router")
        except Exception:
            return []
    except Exception:
        return []

    hellos: list[Any] = []
    try:
        if hasattr(scout, "receiver"):
            recv = scout.receiver
            hellos = list(recv() if callable(recv) else recv)
        elif hasattr(scout, "__iter__"):
            deadline = time.time() + timeout_s
            for hello in scout:
                hellos.append(hello)
                if time.time() >= deadline:
                    break
            if hasattr(scout, "stop"):
                try:
                    scout.stop()
                except Exception:
                    pass
        elif isinstance(scout, list):
            hellos = scout
    except Exception:
        return []

    for hello in hellos:
        what = str(getattr(hello, "whatami", "") or "")
        if what and what != "router":
            continue
        locators = _hello_locators(hello)
        if not locators:
            continue
        zid = str(getattr(hello, "zid", "") or "")
        key = zid or locators[0]
        if key not in found:
            found[key] = ScoutedRouter(zid=zid, whatami=what or "router", locators=locators)
        else:
            for loc in locators:
                if loc not in found[key].locators:
                    found[key].locators.append(loc)
    return list(found.values())


def parse_router_announcement(payload: dict[str, Any] | bytes) -> dict[str, Any] | None:
    """Normalize a ``{fleet}/_fleet/router`` payload, or None if unusable."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = decode_json(payload)
        except Exception:
            return None
    if not isinstance(payload, dict):
        return None
    fleet_id = payload.get("fleet_id") or payload.get("fleet")
    if not fleet_id:
        return None
    locators = payload.get("locators") or []
    if isinstance(locators, str):
        locators = [locators]
    return {
        "fleet_id": str(fleet_id).strip(),
        "locators": [str(x) for x in locators],
        "secure": bool(payload.get("secure", False)),
        "started": payload.get("started"),
        "kind": str(payload.get("kind") or "router"),
    }


def wait_for_router_announcement(
    session: Any,
    fleet: str,
    *,
    timeout_s: float = 2.0,
) -> dict[str, Any] | None:
    """Block until a matching fleet router announcement arrives."""
    key = f"{fleet}/_fleet/{topics.ROUTER}"
    got: list[dict[str, Any]] = []

    def _on_sample(sample: Any) -> None:
        raw = sample.payload.to_bytes() if hasattr(sample.payload, "to_bytes") else sample.payload
        parsed = parse_router_announcement(raw)
        if parsed is not None:
            got.append(parsed)

    sub = session.declare_subscriber(key, _on_sample)
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if got:
                return got[-1]
            time.sleep(0.05)
        return None
    finally:
        try:
            sub.undeclare()
        except Exception:
            pass


def verify_candidate(
    locator: str,
    fleet: str,
    *,
    timeout_s: float = 2.0,
    user: str | None = None,
    password: str | None = None,
    secure: bool = False,
    open_fn: OpenFn | None = None,
) -> dict[str, Any] | None:
    """Open a client session to ``locator`` and wait for a fleet announcement."""
    if open_fn is None:
        from .session import _open_zenoh

        opener: OpenFn = lambda loc: _open_zenoh(
            loc, user=user, password=password, fleet=fleet, secure=secure
        )
    else:
        opener = open_fn
    session = opener(locator)
    try:
        return wait_for_router_announcement(session, fleet, timeout_s=timeout_s)
    finally:
        try:
            session.close()
        except Exception:
            pass


def resolve_auto_connect(
    fleet: str,
    *,
    extra: str | list[str] | None = None,
    scout_fn: ScoutFn | None = None,
    verify_fn: VerifyFn | None = None,
    timeout_s: float = 2.0,
    scout_timeout_s: float = 1.0,
    user: str | None = None,
    password: str | None = None,
    secure: bool = False,
) -> str:
    """Scout, then accept the first candidate whose announcement matches ``fleet``.

    ``extra`` locators (explicit fallbacks) are tried first. Raises
    ``RuntimeError`` listing each candidate and the fleet it announced
    (or ``unknown`` when nothing was published).
    """
    candidates: list[str] = []
    if isinstance(extra, str):
        candidates.extend(split_connect_list(extra))
    elif extra:
        for item in extra:
            candidates.extend(split_connect_list(str(item)))

    hellos = scout_routers(timeout_s=scout_timeout_s, scout_fn=scout_fn)
    for hello in hellos:
        for loc in hello.locators:
            if loc not in candidates:
                candidates.append(loc)

    verifier = verify_fn or (
        lambda loc, fl: verify_candidate(
            loc,
            fl,
            timeout_s=timeout_s,
            user=user,
            password=password,
            secure=secure,
        )
    )

    tried: list[tuple[str, str]] = []
    if not candidates:
        # Fallback: omit endpoints and verify after autoconnect.
        ann = verifier("auto", fleet)
        if ann and ann.get("fleet_id") == fleet:
            locators = ann.get("locators") or []
            chosen = locators[0] if locators else "auto"
            print(
                f"Rosie: discovered router fleet={fleet} connect={chosen} (scout fallback)",
                flush=True,
            )
            return str(chosen)
        tried.append(("auto", str((ann or {}).get("fleet_id") or "unknown")))
    else:
        for loc in candidates:
            ann = verifier(loc, fleet)
            if ann and ann.get("fleet_id") == fleet:
                print(
                    f"Rosie: discovered router fleet={fleet} connect={loc}",
                    flush=True,
                )
                return loc
            tried.append((loc, str((ann or {}).get("fleet_id") or "unknown")))

    detail = ", ".join(f"{loc}→{fid}" for loc, fid in tried) or "none"
    raise RuntimeError(
        f"no router announced fleet {fleet!r} "
        f"(candidates: {detail}). "
        "Is `rosie router --fleet` running on this LAN, and is multicast allowed? "
        "Fallback: set connect to tcp/<router-host-ip>:7447."
    )


def router_announcement(
    fleet: str,
    *,
    locators: list[str],
    secure: bool,
    started: float,
) -> dict[str, Any]:
    """Payload for ``{fleet}/_fleet/router``."""
    return {
        "fleet_id": fleet,
        "kind": "router",
        "locators": list(locators),
        "secure": bool(secure),
        "started": float(started),
    }
