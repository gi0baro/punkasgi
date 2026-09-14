"""Doubles for the httpunk surface the HTTP bridge touches; no httpunk code runs."""

from __future__ import annotations

import tonio.colored as tonio
from httpunk import HeaderMap, Version

from punkasgi.config import Config
from punkasgi.lifespan.off import LifespanOff
from punkasgi.protocols.http import Connection, handle


class FakeSendStream:
    def __init__(self, request):
        self.request = request
        self.data = []
        self.trailers = None
        self.reset = False
        self.done = False

    @property
    def body(self):
        return b"".join(self.data)

    async def send_data(self, chunk, end_stream=False):
        self._check_open()
        self.data.append(bytes(chunk))
        if end_stream:
            self.done = True

    async def send_trailers(self, trailers):
        self._check_open()
        HeaderMap(trailers)
        self.trailers = [(bytes(name), bytes(value)) for name, value in trailers]
        self.done = True

    async def send_reset(self, reason=None):
        if self.done:
            return
        self.done = True
        self.reset = True

    def _check_open(self):
        if self.done:
            raise RuntimeError("response body already complete")


class FakeRequest:
    def __init__(
        self,
        method="GET",
        target="/",
        headers=None,
        version=Version.HTTP_11,
        body=(),
        *,
        body_error=None,
        send_error=None,
        write_error=None,
        authority=None,
        scheme=None,
        leftover=b"",
    ):
        self.method = method
        self.target = target
        self.path = target
        self.headers = HeaderMap(headers or [])
        self.is_upgrade = method == "CONNECT" or any(name == b"upgrade" for name, _ in self.headers.raw_items())
        self.version = version
        self.authority = authority
        self.scheme = scheme
        self._body = list(body)
        self._body_error = body_error
        self._send_error = send_error
        self._write_error = write_error
        self._leftover = leftover

        self.status = None
        self.response_headers = None
        self.end_stream = None
        self.stream = None
        self.responded = None
        self.reset_called = False
        self.detached = False
        # set by a test to have the client leave (h1 peer_closed / h2 reset_received)
        self.gone = tonio.Event()

    async def aiter_bytes(self):
        for chunk in self._body:
            yield chunk
        if self._body_error is not None:
            raise self._body_error

    def _start(self, status, headers):
        if self.stream is not None or self.responded is not None:
            raise RuntimeError("response already sent for this request")
        # httpunk validates names and values at the head, unless handed a map already built
        if isinstance(headers, HeaderMap):
            pairs = headers.raw_items()
        else:
            HeaderMap(headers or [])
            pairs = list(headers or [])
        if self._send_error is not None:
            raise self._send_error
        self.status = status
        self.response_headers = [(bytes(name), bytes(value)) for name, value in pairs]
        # the head is on the wire and the write fails afterwards (an h2 flow-control error
        # while the body goes out, a transport error under an h1 coalesced write)
        if self._write_error is not None:
            raise self._write_error

    async def send_response(self, status, *, headers=None, end_stream=False, detect_eof=True):
        self._start(status, headers)
        self.end_stream = end_stream
        self.stream = FakeSendStream(self)
        self.stream.done = end_stream
        return self.stream

    async def respond(self, status, *, headers=None, body=None, trailers=None):
        self._start(status, headers)
        self.responded = body or b""

    @property
    def body(self):
        if self.responded is not None:
            return self.responded
        return self.stream.body if self.stream is not None else None

    @property
    def response_complete(self):
        return self.responded is not None or (self.stream is not None and self.stream.done and not self.stream.reset)

    async def peer_closed(self):
        await self.gone.wait()
        return True

    async def reset_received(self):
        await self.gone.wait()
        return 8

    async def reset(self, error_code=None):
        self.reset_called = True

    def detach(self):
        self.detached = True
        return self._leftover


async def run_cycle(app, request, lifespan=None, **kwargs):
    config = Config(app=app, **kwargs)
    config.load()
    lifespan = lifespan or LifespanOff(config)
    connection = Connection(None, ("127.0.0.1", 8000), ("127.0.0.1", 8001), False, config)
    return await handle(request, config, lifespan.state, connection)
