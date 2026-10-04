"""SSRF guard: resolve and validate every hop before connecting.

This guards the CLI, but the CLI exists to fetch URLs a user typed. The
realistic threat is a redirect or a sitemap entry pointing at 169.254.169.254,
so validation happens on the initial URL and on every redirect hop.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_V4 = (
    "0.0.0.0/8",  # this-network
    "10.0.0.0/8",  # private
    "100.64.0.0/10",  # carrier NAT
    "127.0.0.0/8",  # loopback
    "169.254.0.0/16",  # link-local, includes 169.254.169.254 metadata
    "172.16.0.0/12",  # private
    "192.0.0.0/24",  # IETF protocol assignments
    "192.168.0.0/16",  # private
    "198.18.0.0/15",  # benchmarking
    "224.0.0.0/4",  # multicast
    "240.0.0.0/4",  # reserved, includes broadcast
)

BLOCKED_V6 = ("::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8")

_BLOCKED = [ipaddress.ip_network(n) for n in (*BLOCKED_V4, *BLOCKED_V6)]

# The cloud metadata endpoint specifically. Listing it separately keeps the
# intent readable and survives a future refactor of the ranges above.
METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})


class BlockedTarget(Exception):
    """Safety rule violation: exit code 6."""


def is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if str(addr) in METADATA_ADDRESSES:
        return True
    return any(addr in net for net in _BLOCKED)


def resolve_host(host: str) -> list[str]:
    """Resolve a hostname to every address it currently points at.

    All answers are checked, not just the first: a host with both a public and
    a private record would be caught by checking only the first.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise BlockedTarget(f"Could not resolve host {host!r}: {exc}") from exc
    return [str(info[4][0]) for info in infos]


def check_url(url: str, allow_private: bool = False) -> list[str]:
    """Validate a URL's scheme and resolved addresses.

    Returns the resolved addresses so the caller can reuse them. Raises
    BlockedTarget when the target is not allowed.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise BlockedTarget(f"Unsupported URL scheme {parsed.scheme!r}; only http and https")
    host = parsed.hostname
    if not host:
        raise BlockedTarget(f"URL has no host: {url!r}")

    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = resolve_host(host)

    if not addresses:
        raise BlockedTarget(f"Host {host!r} resolved to no addresses")

    if not allow_private:
        bad = [a for a in addresses if is_blocked_ip(a)]
        if bad:
            raise BlockedTarget(
                f"{host} resolves to a private or reserved address ({', '.join(bad)}). "
                "Refusing to fetch it. Pass --allow-private if this is your own machine "
                "(for example localhost:3000)."
            )
    return addresses