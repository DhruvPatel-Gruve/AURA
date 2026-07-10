"""SSRF guard for admin-supplied URLs that the backend then fetches itself.

`POST /setup/test-jsm` accepts an arbitrary `base_url` from an authenticated
admin and immediately makes a server-side HTTP request to it — a textbook
SSRF oracle (cloud metadata endpoints, internal-only services, localhost
ports) even though the caller must already be an admin. Defense-in-depth:
an admin account being phished/compromised shouldn't also hand over a free
internal network probe.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    pass


def _check_sync(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeURLError("URL must use https://")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL must include a hostname")
    if host.lower() == "localhost":
        raise UnsafeURLError("URL host is not allowed")

    try:
        addrinfos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host!r}: {exc}") from exc

    for _family, _type, _proto, _canon, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local  # covers the 169.254.169.254 cloud metadata address
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeURLError(f"URL host {host!r} resolves to a disallowed address ({ip})")


async def assert_safe_external_url(url: str) -> None:
    """Raise UnsafeURLError if `url` is not a safe external HTTPS target.

    DNS resolution is blocking, so it's offloaded to a worker thread —
    calling this from an async route handler must not stall the event loop.
    """
    await asyncio.to_thread(_check_sync, url)
