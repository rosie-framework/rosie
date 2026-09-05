"""LAN address helpers for router-host locator resolution."""

from __future__ import annotations

import socket


def local_ipv4s() -> list[str]:
    """Non-loopback IPv4 addresses, default-route address first when known."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips


def lan_locator(ip: str, port: int = 7447) -> str:
    """Format a Zenoh TCP locator for a LAN address."""
    return f"tcp/{ip}:{port}"
