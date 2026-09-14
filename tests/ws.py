"""A tonio-native WebSocket client over the websockets sans-io ClientProtocol, plus an
in-process stream pair so the bridge can be driven with no socket."""

from __future__ import annotations

import tonio.colored as tonio
from httpunk import Version
from tonio.colored import net, sync
from websockets.client import ClientProtocol
from websockets.frames import Frame, Opcode
from websockets.http11 import Response
from websockets.protocol import CLOSED
from websockets.uri import parse_uri

from punkasgi.config import Config
from punkasgi.protocols.http import Connection
from punkasgi.protocols.websockets import handle
from tests.fakes import FakeRequest


class _End:
    def __init__(self):
        self.closed = False
        self._inbox_send, self._inbox_recv = sync.channel.unbounded()
        self.peer = None

    async def receive_some(self, max_bytes=None):
        data = await self._inbox_recv.receive()
        if data is None:
            raise OSError("stream closed")
        return data

    async def send_all(self, data):
        if self.closed:
            raise OSError("stream closed")
        self.peer._inbox_send.send(bytes(data))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._inbox_send.send(None)
        self.peer._inbox_send.send(b"")


def stream_pair():
    server, client = _End(), _End()
    server.peer, client.peer = client, server
    return server, client


class WebSocketClient:
    def __init__(self, stream, uri="ws://127.0.0.1/", *, subprotocols=None, extensions=None):
        self.stream = stream
        self.protocol = ClientProtocol(parse_uri(uri), subprotocols=subprotocols, extensions=extensions, max_size=None)
        self.request = None
        self.response = None
        self.mute = False
        self._events = []

    def prepare(self, headers=None):
        self.request = self.protocol.connect()
        for name, value in headers or []:
            self.request.headers[name] = value
        self.protocol.send_request(self.request)
        return b"".join(self.protocol.data_to_send())

    async def handshake(self):
        event = await self._next_event()
        assert isinstance(event, Response), event
        self.response = event
        if self.protocol.handshake_exc is not None:
            raise self.protocol.handshake_exc
        return event

    async def connect(self, headers=None):
        await self.stream.send_all(self.prepare(headers))
        return await self.handshake()

    @property
    def subprotocol(self):
        return self.protocol.subprotocol

    @property
    def extensions(self):
        return [extension.name for extension in self.protocol.extensions]

    @property
    def close_code(self):
        return self.protocol.close_code

    @property
    def close_reason(self):
        return self.protocol.close_reason

    async def _write(self):
        out = b"".join(self.protocol.data_to_send())
        if out and not self.mute:
            await self.stream.send_all(out)

    async def _next_event(self):
        while not self._events:
            if self.protocol.state is CLOSED:
                raise self.protocol.close_exc
            try:
                data = await self.stream.receive_some()
            except Exception:
                data = b""
            if data:
                self.protocol.receive_data(data)
            else:
                self.protocol.receive_eof()
            self._events.extend(self.protocol.events_received())
            try:
                await self._write()
            except Exception:
                pass
        return self._events.pop(0)

    async def recv(self):
        while True:
            event = await self._next_event()
            if isinstance(event, Frame) and event.opcode in (Opcode.TEXT, Opcode.BINARY):
                opcode = event.opcode
                data = bytes(event.data)
                while not event.fin:
                    event = await self._next_event()
                    if isinstance(event, Frame) and event.opcode is Opcode.CONT:
                        data += bytes(event.data)
                return data.decode() if opcode is Opcode.TEXT else data

    async def send(self, message):
        if isinstance(message, str):
            self.protocol.send_text(message.encode())
        else:
            self.protocol.send_binary(message)
        await self._write()

    async def send_fragments(self, fragments):
        first, *rest = fragments
        if isinstance(first, str):
            self.protocol.send_text(first.encode(), fin=False)
        else:
            self.protocol.send_binary(first, fin=False)
        for index, fragment in enumerate(rest):
            data = fragment.encode() if isinstance(fragment, str) else fragment
            self.protocol.send_continuation(data, fin=index == len(rest) - 1)
        await self._write()

    async def ping(self):
        self.protocol.send_ping(b"")
        await self._write()

    async def close(self, code=1000, reason=""):
        self.protocol.send_close(code, reason)
        await self._write()
        await self.wait_closed()

    async def wait_closed(self):
        while self.protocol.state is not CLOSED:
            try:
                await self._next_event()
            except Exception:
                return

    def drop(self):
        self.stream.close()


class _Registry(set):
    last = None

    def add(self, connection):
        self.last = connection
        super().add(connection)


class WebSocketSession:
    """Serve `app` on the bridge over an in-process stream pair (no socket), or connect
    to a live server on `port`, and act as the client."""

    def __init__(
        self,
        app=None,
        *,
        port=None,
        headers=None,
        remove_headers=(),
        subprotocols=None,
        extensions=None,
        path="/",
        **config,
    ):
        self.app = app
        self.port = port
        self.headers = headers
        self.remove_headers = remove_headers
        self.subprotocols = subprotocols
        self.extensions = extensions
        self.path = path
        self.config = config
        self.registry = _Registry()
        self.task = None
        self.client = None

    async def __aenter__(self):
        if self.port is not None:
            stream = await net.open_tcp_stream("127.0.0.1", self.port)
            self.client = WebSocketClient(
                stream,
                f"ws://127.0.0.1:{self.port}{self.path}",
                subprotocols=self.subprotocols,
                extensions=self.extensions,
            )
            return self

        config = Config(app=self.app, lifespan="off", **self.config)
        config.load()
        server_end, client_end = stream_pair()
        self.client = WebSocketClient(
            client_end, f"ws://127.0.0.1{self.path}", subprotocols=self.subprotocols, extensions=self.extensions
        )
        self.client.prepare(self.headers)
        request = self.client.request
        for name in self.remove_headers:
            del request.headers[name]
        fake = FakeRequest(
            "GET",
            request.path,
            [(name.encode("ascii"), value.encode("latin-1")) for name, value in request.headers.raw_items()],
            Version.HTTP_11,
        )
        info = Connection(server_end, ("127.0.0.1", 8000), ("127.0.0.1", 8001), False, config)
        self.task = tonio.spawn(handle(fake, b"", config, {}, info, self.registry))
        return self

    async def __aexit__(self, *exc_info):
        self.client.stream.close()
        if self.task is not None:
            await self.task

    async def connect(self):
        if self.port is not None:
            return await self.client.connect(self.headers)
        return await self.client.handshake()

    @property
    def connection(self):
        return self.registry.last

    async def finished(self):
        await self.task
