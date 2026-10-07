"""Connect to the exact public address validated for each new socket.

HTTPcore retains the original origin for Host, TLS SNI and certificate checks;
only the TCP backend receives the validated numeric address. Redirects create
their own origin connection and pass the same policy. Environment proxies are
disabled by callers so they cannot bypass this backend.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, delegate=None, resolver=None):
        self.delegate = delegate or AnyIOBackend()
        self.resolver = resolver

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in {80, 443}:
            raise httpcore.ConnectError("source port is not permitted")
        resolver = self.resolver or asyncio.get_running_loop().getaddrinfo
        try:
            answers = await asyncio.wait_for(resolver(host, port, type=socket.SOCK_STREAM), timeout=timeout or 20)
            addresses = list(dict.fromkeys(str(ipaddress.ip_address(answer[4][0])) for answer in answers))
        except (OSError, ValueError, asyncio.TimeoutError) as exc:
            raise httpcore.ConnectError("source address resolution failed") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise httpcore.ConnectError("source resolves to a non-public address")
        last_error = None
        for address in addresses:
            try:
                return await self.delegate.connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError("source connection failed")

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("unix source sockets are forbidden")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class PublicHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicNetworkBackend(),
            max_connections=10, max_keepalive_connections=5, keepalive_expiry=5,
        )
