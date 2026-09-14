"""
Derived from uvicorn (https://github.com/Kludex/uvicorn), distributed under the
following license:

Copyright © 2017-present, Encode OSS Ltd. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from __future__ import annotations

import functools
import ipaddress

from punkasgi._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, Scope


class ProxyHeadersMiddleware:
    def __init__(self, app: ASGI3Application, trusted_hosts: list[str] | str = "127.0.0.1") -> None:
        self.app = app
        self.trusted_hosts = _TrustedHosts(trusted_hosts)

    async def __call__(self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)

        client_addr = scope.get("client")
        client_host = client_addr[0] if client_addr else None

        if client_host in self.trusted_hosts:
            x_forwarded_proto_value = None
            x_forwarded_for_values = []
            for name, value in scope["headers"]:
                if name == b"x-forwarded-proto":
                    x_forwarded_proto_value = value
                elif name == b"x-forwarded-for":
                    x_forwarded_for_values.append(value)

            if x_forwarded_proto_value is not None:
                x_forwarded_proto = x_forwarded_proto_value.decode("latin1").strip()

                if x_forwarded_proto in {"http", "https", "ws", "wss"}:
                    if scope["type"] == "websocket":
                        scope["scheme"] = x_forwarded_proto.replace("http", "ws")
                    else:
                        scope["scheme"] = x_forwarded_proto

            if x_forwarded_for_values:
                x_forwarded_for = b", ".join(x_forwarded_for_values).decode("latin1")
                host, port = self.trusted_hosts.get_trusted_client_address(x_forwarded_for)

                # an empty x-forwarded-for yields an empty host: keep the transport client then
                if host:
                    scope["client"] = (host, port)

        return await self.app(scope, receive, send)


def _parse_raw_hosts(value):
    return [item.strip() for item in value.split(",")]


def _parse_host_port(value):
    # bare IPs, IPv4 `host:port` and bracketed IPv6 `[host]:port`; anything malformed keeps
    # the value as host with no port, so trust checks never normalise arbitrary input
    if value.startswith("["):
        bracket_end = value.find("]")
        if bracket_end == -1:
            return value, 0

        host = value[1:bracket_end]
        remainder = value[bracket_end + 1 :]
        if not remainder:
            return host, 0
        if not remainder.startswith(":"):
            return value, 0

        try:
            return host, int(remainder[1:])
        except ValueError:
            return host, 0

    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return value, 0

    return value, 0


class _TrustedHosts:
    def __init__(self, trusted_hosts):
        self.always_trust = trusted_hosts in ("*", ["*"])

        # addresses are compared as objects (an IPv6 address has many spellings) and kept apart
        # from networks (a set lookup beats a membership test per network); literals cover
        # non-IP peers such as unix socket paths
        self.trusted_literals = set()
        self.trusted_hosts = set()
        self.trusted_networks = set()

        if not self.always_trust:
            if isinstance(trusted_hosts, str):
                trusted_hosts = _parse_raw_hosts(trusted_hosts)

            for host in trusted_hosts:
                if "/" in host:
                    try:
                        self.trusted_networks.add(ipaddress.ip_network(host))
                    except ValueError:
                        self.trusted_literals.add(host)
                else:
                    try:
                        self.trusted_hosts.add(ipaddress.ip_address(host))
                    except ValueError:
                        self.trusted_literals.add(host)

        self._trusts = functools.lru_cache(maxsize=4096)(self._compute_trust)

    def __contains__(self, host):
        if self.always_trust:
            return True

        if not host:
            return False

        # longer than a DNS name: never trusted, and not worth pinning as a cache key
        if len(host) > 253:
            return self._compute_trust(host)

        return self._trusts(host)

    def _compute_trust(self, host):
        try:
            ip = ipaddress.ip_address(host)
            return ip in self.trusted_hosts or any(ip in net for net in self.trusted_networks)
        except ValueError:
            return host in self.trusted_literals

    def get_trusted_client_address(self, x_forwarded_for):
        x_forwarded_for_hosts = _parse_raw_hosts(x_forwarded_for)

        if self.always_trust:
            return _parse_host_port(x_forwarded_for_hosts[0])

        # each proxy appends to the list, so the first untrusted host from the right is the client
        for host_port in reversed(x_forwarded_for_hosts):
            host, port = _parse_host_port(host_port)
            if host not in self:
                return host, port

        # every hop was trusted: the client itself is a trusted proxy
        return _parse_host_port(x_forwarded_for_hosts[0])
