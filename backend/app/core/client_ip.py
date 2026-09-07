"""Resolve client addresses without trusting spoofable proxy headers by default."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence


def resolve_client_ip(
    *,
    peer_host: str | None,
    forwarded_for: str | None,
    trusted_proxies: Sequence[str],
) -> str:
    peer = peer_host or "unknown"
    if not forwarded_for or not trusted_proxies:
        return peer
    try:
        peer_address = ipaddress.ip_address(peer)
        networks = tuple(ipaddress.ip_network(value, strict=False) for value in trusted_proxies)
        hops = tuple(
            ipaddress.ip_address(value.strip()) for value in forwarded_for.split(",")
        )
    except ValueError:
        return peer
    if not any(peer_address in network for network in networks):
        return peer
    for hop in reversed(hops):
        if not any(hop in network for network in networks):
            return str(hop)
    return peer
