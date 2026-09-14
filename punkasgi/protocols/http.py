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

import contextlib
import logging
import threading
from urllib.parse import unquote

import tonio.colored as tonio
from httpunk import (
    ConnectionClosedError,
    GoAwayError,
    H1BodyError,
    H1IncompleteMessageError,
    HeaderMap,
    StreamResetError,
    Version,
)

from punkasgi._types import ASGIReceiveEvent, ASGISendEvent
from punkasgi.logging import TRACE_LOG_LEVEL
from punkasgi.protocols.utils import get_client_addr, get_path_with_query_string


# handle()'s verdict for an h1 connection that must not be reused
CLOSE = object()


# handle()'s verdict for a WebSocket upgrade: the transport is the caller's now
class Detached:
    __slots__ = ("leftover", "request")

    def __init__(self, request, leftover):
        self.request = request
        self.leftover = leftover


_DISCONNECT = {"type": "http.disconnect"}
_BODY_END = {"type": "http.request", "body": b"", "more_body": False}
_CLIENT_GONE = (H1IncompleteMessageError, ConnectionClosedError, StreamResetError, GoAwayError)
_HTTP_10, _HTTP_11, _HTTP_2 = Version.HTTP_10, Version.HTTP_11, Version.HTTP_2
# shared by every scope: an app mutating them is misbehaving
_ASGI = {"version": "3.0", "spec_version": "2.4"}
_EXTENSIONS = {"http.response.trailers": {}}

logger = logging.getLogger("punkasgi.error")
access_logger = logging.getLogger("punkasgi.access")


class Connection:
    __slots__ = ("client", "scheme", "scope", "server", "tls", "transport")

    def __init__(self, transport, server, client, tls, config):
        self.transport = transport
        self.server = server
        self.client = client
        self.tls = tls
        self.scheme = "https" if tls else "http"
        # the scope template: everything constant on the connection, copied per request
        self.scope = {
            "type": "http",
            "asgi": _ASGI,
            "http_version": "1.1",
            "server": server,
            "client": client,
            "scheme": self.scheme,
            "method": None,
            "root_path": config.root_path,
            "path": None,
            "raw_path": None,
            "query_string": None,
            "headers": None,
            "state": None,
            "extensions": _EXTENSIONS,
        }


def _upgrade(headers):
    connection = []
    upgrade = None
    for name, value in headers:
        if name == b"connection":
            connection = [token.lower().strip() for token in value.split(b",")]
        elif name == b"upgrade":
            upgrade = value.lower()
    if b"upgrade" in connection:
        return upgrade
    return None


async def handle(request, config, app_state, conn):
    version = request.version
    headers = request.headers.raw_items()
    scope = conn.scope.copy()
    if version is _HTTP_11:
        h2 = False
        target = request.path
    elif version is _HTTP_2:
        h2 = True
        scope["http_version"] = "2"
        scheme = request.scheme
        if scheme:
            scope["scheme"] = scheme
        # the ASGI spec wants `host` in the headers on HTTP/2, built from `:authority`
        authority = request.authority
        if authority is not None:
            host = (b"host", authority.encode("latin-1"))
            if b"host" in request.headers:
                headers = [host] + [pair for pair in headers if pair[0] != b"host"]
            else:
                headers.insert(0, host)
        target = request.path or ""
    else:
        h2 = False
        scope["http_version"] = "1.0"
        target = request.path
    raw_path, _, query_string = target.partition("?")
    root_path = config.root_path
    scope["method"] = request.method
    scope["path"] = root_path + (raw_path if "%" not in raw_path else unquote(raw_path))
    scope["raw_path"] = config.root_path_bytes + raw_path.encode("ascii")
    scope["query_string"] = query_string.encode("ascii")
    scope["headers"] = headers
    scope["state"] = app_state.copy()

    if not h2 and request.is_upgrade:
        upgrade = _upgrade(headers)
        if upgrade == b"websocket":
            if config.ws:
                if logger.level <= TRACE_LOG_LEVEL:
                    prefix = "%s:%d - " % conn.client if conn.client else ""
                    logger.log(TRACE_LOG_LEVEL, "%sUpgrading to WebSocket", prefix)
                return Detached(request, request.detach())
            logger.warning("Unsupported upgrade request.")
            await request.respond(
                400,
                headers=[(b"content-type", b"text/plain; charset=utf-8"), (b"connection", b"close")],
                body=b"Unsupported upgrade request.",
            )
            return CLOSE

    cycle = RequestResponseCycle(request, scope, config.encoded_headers, config.access_logging, h2)
    await cycle.run_asgi(config.loaded_app)
    return CLOSE if cycle.close_connection else None


# the response side, in order: nothing sent; the start message held; the head on the wire
# (`respond()` entered or a `SendStream` open); trailers awaited; complete; client gone
_START, _HEAD, _BODY, _TRAILERS, _COMPLETE, _GONE = range(6)

_500_HEADERS = [(b"content-type", b"text/plain; charset=utf-8")]
_500_HEADERS_H1 = _500_HEADERS + [(b"connection", b"close")]


def _unexpected(expected, message_type):
    return RuntimeError(f"Expected ASGI message '{expected}', but got '{message_type}'.")


class RequestResponseCycle:
    __slots__ = (
        "_lock",
        "access_log",
        "body",
        "body_done",
        "close_connection",
        "default_headers",
        "done",
        "expect_trailers",
        "h2",
        "head",
        "request",
        "scope",
        "state",
        "stream",
        "trailers",
    )

    def __init__(self, request, scope, default_headers, access_log, h2):
        self.request = request
        self.scope = scope
        self.h2 = h2
        self.default_headers = default_headers
        self.access_log = access_log
        # an app may call `receive()` from a sibling task while it sends from another, on
        # another thread: transitions run under a lock so the client-gone state stays sticky;
        # reads are plain, since the only concurrent transition is to `_GONE` and every locked
        # transition preserves it, a stale read ends in a refused transition or a failed write
        self._lock = threading.Lock()
        self.state = _START
        self.close_connection = False
        # the body iterator exists only once `receive()` needs it
        self.body = None
        self.body_done = False
        self.done = tonio.Event()
        # the head is held until the first body message: a single-shot response goes out
        # as one `respond()`, a streamed one opens a `SendStream` (granian defers the same way)
        self.head = None
        self.stream = None
        self.expect_trailers = False
        self.trailers = None

    async def run_asgi(self, app):
        try:
            result = await app(self.scope, self.receive, self.send)
        except Exception as exc:
            logger.error("Exception in ASGI application\n", exc_info=exc)
            if self.state >= _BODY:
                await self.abort()
            else:
                await self.send_500_response()
        else:
            state = self.state
            if result is not None:
                logger.error("ASGI callable should return None, but returned '%s'.", result)
                await self.abort()
            elif state == _START:
                logger.error("ASGI callable returned without starting response.")
                await self.send_500_response()
            elif state < _COMPLETE:
                logger.error("ASGI callable returned without completing response.")
                if state == _HEAD:
                    await self.send_500_response()
                else:
                    await self.abort()
        finally:
            self.done.set()

    async def send_500_response(self):
        headers = self.default_headers + (_500_HEADERS if self.h2 else _500_HEADERS_H1)
        self._set_state(_BODY)
        if self.access_log:
            self._log_access(500)
        try:
            await self.request.respond(500, headers=headers, body=b"Internal Server Error")
        except _CLIENT_GONE:
            self._gone()
            return
        self._complete()

    async def abort(self):
        with contextlib.suppress(Exception):
            stream = self.stream
            if stream is not None:
                await stream.send_reset()
            elif self.h2:
                await self.request.reset()
        if not self.h2:
            self.close_connection = True
        self.done.set()

    def _log_access(self, status):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            get_client_addr(self.scope),
            self.scope["method"],
            get_path_with_query_string(self.scope),
            self.scope["http_version"],
            status,
        )

    def _set_state(self, state):
        with self._lock:
            if self.state != _GONE:
                self.state = state

    def _complete(self):
        self._set_state(_COMPLETE)
        self.done.set()

    def _gone(self):
        with self._lock:
            self.state = _GONE
        self.done.set()

    async def send(self, message: ASGISendEvent) -> None:
        message_type = message["type"]
        state = self.state

        if state == _HEAD or state == _BODY:
            if message_type != "http.response.body":
                raise _unexpected("http.response.body", message_type)
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            end_stream = not more_body and not self.expect_trailers
            try:
                if state == _HEAD:
                    status, headers = self.head
                    self._set_state(_BODY)
                    if end_stream:
                        await self.request.respond(status, headers=headers, body=body)
                        self._complete()
                        return
                    self.stream = await self.request.send_response(status, headers=headers, detect_eof=False)
                await self.stream.send_data(body, end_stream=end_stream)
            except _CLIENT_GONE:
                self._gone()
                return
            if end_stream:
                self._complete()
            elif not more_body:
                self._set_state(_TRAILERS)

        elif state == _START:
            if message_type != "http.response.start":
                raise _unexpected("http.response.start", message_type)
            status = message["status"]
            headers = message.get("headers")
            if headers is None:
                headers = self.default_headers
            elif isinstance(headers, list):
                headers = self.default_headers + headers
            else:
                headers = self.default_headers + list(headers)
            # the map httpunk would build anyway, built here: its lookups drive the stream
            # decision, and an invalid name or value fails now, with nothing on the wire
            headers = HeaderMap(headers)
            self.expect_trailers = bool(message.get("trailers", False))
            if self.access_log:
                self._log_access(status)
            # a response of unknown length is a stream, and so is an event stream whatever it
            # declares: its head goes out now (hyper flushes a head whose body is pending;
            # uvicorn writes every head at once). A response of known length is held until
            # its first body message, which for a single-shot response is the whole body:
            # one coalesced write instead of two (granian peeks the same way, on the
            # content-type only)
            stream = b"content-length" not in headers
            if not stream:
                content_type = headers.get(b"content-type")
                stream = content_type is not None and content_type[:17] == b"text/event-stream"
            # `detect_eof=False`: a client leaving mid-response is observed through
            # `receive()` (`peer_closed()`, which arms the read on demand), not by the
            # head's own watcher; an app that never asks sees a FIN one write later, at the RST
            if stream:
                self._set_state(_BODY)
                try:
                    self.stream = await self.request.send_response(status, headers=headers, detect_eof=False)
                except _CLIENT_GONE:
                    self._gone()
            else:
                self.head = (status, headers)
                self._set_state(_HEAD)

        elif state == _TRAILERS:
            if message_type != "http.response.trailers":
                raise _unexpected("http.response.trailers", message_type)
            trailers = self.trailers
            if trailers is None:
                trailers = self.trailers = []
            trailers.extend(message.get("headers", []))
            if not message.get("more_trailers", False):
                try:
                    await self.stream.send_trailers(trailers)
                except _CLIENT_GONE:
                    self._gone()
                    return
                self._complete()

        elif state == _COMPLETE:
            raise RuntimeError(f"Unexpected ASGI message '{message_type}' sent, after response already completed.")

        # _GONE: the client left, nothing to send it

    async def receive(self) -> ASGIReceiveEvent:
        state = self.state
        if state >= _COMPLETE:
            return _DISCONNECT

        if not self.body_done:
            body = self.body
            if body is None:
                body = self.body = self.request.aiter_bytes()
            try:
                chunk = await anext(body)
            except StopAsyncIteration:
                self.body_done = True
                return _BODY_END
            except (H1BodyError, *_CLIENT_GONE):
                with self._lock:
                    self.state = _GONE
                return _DISCONNECT
            return {"type": "http.request", "body": chunk, "more_body": True}

        # uvicorn parks here until the client leaves or the response completes,
        # and answers with a disconnect either way
        if await tonio.select(self._client_gone(), self._response_done()):
            with self._lock:
                self.state = _GONE
        return _DISCONNECT

    async def _client_gone(self):
        if self.h2:
            with contextlib.suppress(Exception):
                await self.request.reset_received()
            return True
        return await self.request.peer_closed()

    async def _response_done(self):
        await self.done.wait()
        return False
