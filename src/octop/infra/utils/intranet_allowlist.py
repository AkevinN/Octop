"""Deployment-level intranet exceptions to the outbound SSRF guard.

``infra/utils`` must not read ``octop.config`` (AGENTS.md §5): ``OctopServer`` and
``open_cli_services`` inject the ``intranet_allow_*`` keys via
:func:`configure_intranet_allowlist`. The empty default keeps the guard upstream.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Never allowlistable: unspecified, loopback, link-local (cloud metadata), multicast,
# reserved, and the IPv4-mapped block (mapped addresses are matched as IPv4 instead).
_HARD_DENY = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "::ffff:0:0/96",
        "fe80::/10",
        "ff00::/8",
    )
)


@dataclass(frozen=True)
class IntranetAllowlist:
    networks: tuple[IPNetwork, ...] = ()
    host_suffixes: tuple[str, ...] = ()
    allow_http: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.networks

    def permits_ip(self, addr: IPAddress) -> bool:
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in net for net in self.networks)

    def trusts_host(self, host: str) -> bool:
        """An allowlisted IP literal, or a name under a suffix on a label boundary."""
        try:
            return self.permits_ip(ipaddress.ip_address(host))
        except ValueError:
            return any(host == s or host.endswith(f".{s}") for s in self.host_suffixes)


_current = IntranetAllowlist()


def _network(raw: str) -> IPNetwork:
    try:
        net = ipaddress.ip_network(raw)
    except ValueError as exc:
        raise ValueError(f"intranet_allow_cidrs: invalid entry {raw!r} ({exc})") from exc
    for denied in _HARD_DENY:
        if net.overlaps(denied):
            raise ValueError(f"intranet_allow_cidrs: invalid entry {raw!r} (overlaps {denied})")
    return net


def _suffix(raw: str) -> str:
    suffix = raw.strip().lower().strip(".")
    labels = suffix.split(".")
    # A numeric last label rules out IPv4 literals; ':' rules out IPv6 ones.
    if (
        len(labels) < 2
        or not all(labels)
        or labels[-1].isdigit()
        or labels[-1] == "localhost"
        or any(c in "*/:" or c.isspace() for c in suffix)
    ):
        raise ValueError(f"intranet_allow_host_suffixes: invalid entry {raw!r}")
    return suffix


def configure_intranet_allowlist(
    *,
    cidrs: Iterable[str] = (),
    host_suffixes: Iterable[str] = (),
    allow_http: bool = False,
) -> IntranetAllowlist:
    """Validate and install the allowlist; on error the current one stays. No args = reset."""
    global _current
    networks = tuple(dict.fromkeys(_network(c) for c in cidrs))
    suffixes = tuple(dict.fromkeys(_suffix(s) for s in host_suffixes))
    if not networks and (suffixes or allow_http):
        key = "intranet_allow_host_suffixes" if suffixes else "intranet_allow_http"
        raise ValueError(f"{key} requires intranet_allow_cidrs")
    _current = IntranetAllowlist(networks, suffixes, allow_http)
    return _current


def current_intranet_allowlist() -> IntranetAllowlist:
    return _current
