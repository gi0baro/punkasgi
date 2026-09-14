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

from copy import deepcopy

import pytest
import tonio.colored as tonio
import websockets.exceptions
from websockets.extensions.permessage_deflate import ClientPerMessageDeflateFactory
from websockets.frames import Opcode

from punkasgi.config import Config
from punkasgi.protocols.websockets import WebSocketConnection
from tests.response import Response
from tests.utils import run_server
from tests.ws import WebSocketSession


class WebSocketResponse:
    def __init__(self, scope, receive, send):
        self.scope = scope
        self.receive = receive
        self.send = send

    def __await__(self):
        return self.asgi().__await__()

    async def asgi(self):
        while True:
            message = await self.receive()
            message_type = message["type"].replace(".", "_")
            handler = getattr(self, message_type, None)
            if handler is not None:
                await handler(message)
            if message_type == "websocket_disconnect":
                break


class AcceptApp(WebSocketResponse):
    async def websocket_connect(self, message):
        await self.send({"type": "websocket.accept"})


async def accept_then_close_app(scope, receive, send):
    await receive()
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.close", "code": 1000})


def wrap_finished(app, finished):
    async def wrapper(scope, receive, send):
        try:
            return await app(scope, receive, send)
        finally:
            finished.set()

    return wrapper


async def test_invalid_upgrade():
    def app(scope):
        return None

    async with WebSocketSession(app, remove_headers=["Sec-WebSocket-Key"]) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
    response = exc_info.value.response
    assert response.status_code == 400
    assert response.body.decode().lower().strip().rstrip(".") in [
        "missing sec-websocket-key header",
        "failed to open a websocket connection: missing sec-websocket-key header",
    ]


async def test_accept_connection():
    async with WebSocketSession(AcceptApp) as session:
        response = await session.connect()
        assert response.status_code == 101


async def test_shutdown(unused_tcp_port):
    config = Config(app=AcceptApp, lifespan="off", port=unused_tcp_port)
    async with run_server(config) as server:
        async with WebSocketSession(port=unused_tcp_port) as session:
            await session.connect()
            server.exit.set()
            await session.client.wait_closed()
            assert session.client.close_code == 1012


async def test_supports_permessage_deflate_extension():
    async with WebSocketSession(AcceptApp, extensions=[ClientPerMessageDeflateFactory()]) as session:
        await session.connect()
        assert "permessage-deflate" in session.client.extensions


async def test_can_disable_permessage_deflate_extension():
    async with WebSocketSession(
        AcceptApp, extensions=[ClientPerMessageDeflateFactory()], ws_per_message_deflate=False
    ) as session:
        await session.connect()
        assert "permessage-deflate" not in session.client.extensions


async def test_close_connection():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.close"})

    async with WebSocketSession(App) as session:
        with pytest.raises(websockets.exceptions.InvalidHandshake):
            await session.connect()


async def test_headers():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            headers = dict(self.scope.get("headers"))
            assert headers[b"host"].startswith(b"127.0.0.1")
            assert headers[b"username"] == bytes("abraão", "utf-8")
            await self.send({"type": "websocket.accept"})

    # websockets encodes header values with ISO-8859-1
    username = "abraão".encode().decode("latin-1")
    async with WebSocketSession(App, headers=[("username", username)]) as session:
        response = await session.connect()
        assert response.status_code == 101


async def test_extra_headers():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept", "headers": [(b"extra", b"header")]})

    async with WebSocketSession(App) as session:
        response = await session.connect()
        assert response.headers.get("extra") == "header"


async def test_path_and_raw_path():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            assert self.scope.get("path") == "/one/two"
            assert self.scope.get("raw_path") == b"/one%2Ftwo"
            await self.send({"type": "websocket.accept"})

    async with WebSocketSession(App, path="/one%2Ftwo") as session:
        response = await session.connect()
        assert response.status_code == 101


async def test_send_text_data_to_client():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})

    async with WebSocketSession(App) as session:
        await session.connect()
        assert await session.client.recv() == "123"


async def test_send_binary_data_to_client():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "bytes": b"123"})

    async with WebSocketSession(App) as session:
        await session.connect()
        assert await session.client.recv() == b"123"


async def test_send_and_close_connection():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})
            await self.send({"type": "websocket.close"})

    async with WebSocketSession(App) as session:
        await session.connect()
        assert await session.client.recv() == "123"
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()


async def test_send_text_data_to_server():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _text = message.get("text")
            assert _text is not None
            await self.send({"type": "websocket.send", "text": _text})

    async with WebSocketSession(App) as session:
        await session.connect()
        await session.client.send("abc")
        assert await session.client.recv() == "abc"


async def test_send_binary_data_to_server():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _bytes = message.get("bytes")
            assert _bytes is not None
            await self.send({"type": "websocket.send", "bytes": _bytes})

    async with WebSocketSession(App) as session:
        await session.connect()
        await session.client.send(b"abc")
        assert await session.client.recv() == b"abc"


async def test_send_after_protocol_close():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            await self.send({"type": "websocket.send", "text": "123"})
            await self.send({"type": "websocket.close"})
            with pytest.raises(Exception):
                await self.send({"type": "websocket.send", "text": "123"})

    async with WebSocketSession(App) as session:
        await session.connect()
        assert await session.client.recv() == "123"
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()


async def test_missing_handshake():
    async def app(scope, receive, send):
        pass

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        assert exc_info.value.response.status_code == 500


async def test_send_before_handshake():
    async def app(scope, receive, send):
        await send({"type": "websocket.send", "text": "123"})

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        assert exc_info.value.response.status_code == 500


async def test_duplicate_handshake():
    async def app(scope, receive, send):
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.accept"})

    async with WebSocketSession(app) as session:
        await session.connect()
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()
        assert session.client.close_code == 1006


async def test_asgi_return_value():
    async def app(scope, receive, send):
        await send({"type": "websocket.accept"})
        return 123

    async with WebSocketSession(app) as session:
        await session.connect()
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()
        assert session.client.close_code == 1006


async def test_close_transport_on_asgi_return():
    async def app(scope, receive, send):
        message = await receive()
        if message["type"] == "websocket.connect":
            await send({"type": "websocket.accept"})

    async with WebSocketSession(app) as session:
        await session.connect()
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()
        assert session.client.close_code == 1006


@pytest.mark.parametrize("code", [None, 1000, 1001])
@pytest.mark.parametrize("reason", [None, "test", False], ids=["none_as_reason", "normal_reason", "without_reason"])
async def test_app_close(code, reason):
    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.receive":
                reply = {"type": "websocket.close"}

                if code is not None:
                    reply["code"] = code

                if reason is not False:
                    reply["reason"] = reason

                await send(reply)
            elif message["type"] == "websocket.disconnect":
                break

    async with WebSocketSession(app) as session:
        await session.connect()
        await session.client.ping()
        await session.client.send("abc")
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await session.client.recv()
        assert session.client.close_code == (code or 1000)
        assert session.client.close_reason == (reason or "")


async def test_client_close():
    disconnect_message = None

    async def app(scope, receive, send):
        nonlocal disconnect_message
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.receive":
                pass
            elif message["type"] == "websocket.disconnect":
                disconnect_message = message
                break

    async with WebSocketSession(app) as session:
        await session.connect()
        await session.client.ping()
        await session.client.send("abc")
        await session.client.close(code=1001, reason="custom reason")

    assert disconnect_message == {"type": "websocket.disconnect", "code": 1001, "reason": "custom reason"}


async def test_client_connection_lost():
    got_disconnect_event = tonio.Event()

    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                break

        got_disconnect_event.set()

    async with WebSocketSession(app, ws_ping_interval=0.0) as session:
        await session.connect()
        session.client.drop()
        await got_disconnect_event.wait()


async def test_client_connection_lost_on_send():
    disconnect = tonio.Event()
    got_disconnect_event = False

    async def app(scope, receive, send):
        nonlocal got_disconnect_event
        message = await receive()
        if message["type"] == "websocket.connect":
            await send({"type": "websocket.accept"})
        try:
            await disconnect.wait()
            await send({"type": "websocket.send", "text": "123"})
        except OSError:
            got_disconnect_event = True

    async with WebSocketSession(app) as session:
        await session.connect()
        session.client.drop()
        await tonio.sleep(0.05)
        disconnect.set()

    assert got_disconnect_event is True


async def test_connection_lost_before_handshake_complete():
    send_accept_task = tonio.Event()
    disconnect_message = {}

    async def app(scope, receive, send):
        nonlocal disconnect_message
        message = await receive()
        if message["type"] == "websocket.connect":
            await send_accept_task.wait()
        disconnect_message = await receive()

    async with WebSocketSession(app) as session:
        session.client.drop()
        await tonio.sleep(0.05)
        send_accept_task.set()

    assert disconnect_message == {"type": "websocket.disconnect", "code": 1006}


async def test_send_close_on_server_shutdown(unused_tcp_port):
    disconnect_message = {}

    async def app(scope, receive, send):
        nonlocal disconnect_message
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                disconnect_message = message
                break

    config = Config(app=app, lifespan="off", port=unused_tcp_port)
    async with run_server(config) as server:
        async with WebSocketSession(port=unused_tcp_port) as session:
            await session.connect()
            await tonio.sleep(0.1)
            disconnect_message_before_shutdown = disconnect_message
            server.exit.set()
            await session.client.wait_closed()
            close_code = session.client.close_code

    assert close_code == 1012
    assert disconnect_message_before_shutdown == {}
    assert disconnect_message == {"type": "websocket.disconnect", "code": 1012}


@pytest.mark.parametrize("subprotocol", ["proto1", "proto2"])
async def test_subprotocols(subprotocol):
    advertised_subprotocols = None

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            nonlocal advertised_subprotocols
            assert self.scope["type"] == "websocket"
            advertised_subprotocols = list(self.scope["subprotocols"])
            await self.send({"type": "websocket.accept", "subprotocol": subprotocol})

    async with WebSocketSession(App, subprotocols=["proto1", "proto2"]) as session:
        await session.connect()
        assert session.client.subprotocol == subprotocol
        assert advertised_subprotocols == ["proto1", "proto2"]


MAX_WS_BYTES = 1024 * 1024 * 16
MAX_WS_BYTES_PLUS1 = MAX_WS_BYTES + 1


@pytest.mark.parametrize(
    "client_size_sent, server_size_max, expected_result",
    [
        (MAX_WS_BYTES, MAX_WS_BYTES, 0),
        (MAX_WS_BYTES_PLUS1, MAX_WS_BYTES, 1009),
        (10, 10, 0),
        (11, 10, 1009),
    ],
    ids=[
        "max=defaults sent=defaults",
        "max=defaults sent=defaults+1",
        "max=10 sent=10",
        "max=10 sent=11",
    ],
)
async def test_send_binary_data_to_server_bigger_than_default(client_size_sent, server_size_max, expected_result):
    disconnect_code = None

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})

        async def websocket_receive(self, message):
            _bytes = message.get("bytes")
            assert _bytes is not None
            await self.send({"type": "websocket.send", "bytes": _bytes})

        async def websocket_disconnect(self, message):
            nonlocal disconnect_code
            disconnect_code = message["code"]

    # no compression, so `ws_max_size` applies to the sizes sent on the wire
    async with WebSocketSession(App, ws_max_size=server_size_max, ws_per_message_deflate=False) as session:
        await session.connect()
        if expected_result == 0:
            await session.client.send(b"\x01" * client_size_sent)
            data = await session.client.recv()
            assert data == b"\x01" * client_size_sent
        else:
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await session.client.send(b"\x01" * client_size_sent)
                await session.client.recv()

    if expected_result != 0:
        assert disconnect_code == expected_result


async def test_fragmented_message_exceeding_max_size():
    async with WebSocketSession(AcceptApp, ws_max_size=2048) as session:
        await session.connect()
        payload = b"A" * 1024
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await session.client.send_fragments([payload] * 64)
            await session.client.recv()
    assert exc_info.value.rcvd is not None
    assert exc_info.value.rcvd.code == 1009


@pytest.mark.parametrize("opcode", [Opcode.TEXT, Opcode.BINARY])
async def test_fragmented_message_reassembly(opcode):
    received = []

    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        connect = await receive()
        assert connect["type"] == "websocket.connect"
        await send({"type": "websocket.accept"})
        message = await receive()
        assert message["type"] == "websocket.receive"
        if opcode is Opcode.TEXT:
            payload = message.get("text")
            assert isinstance(payload, str)
        else:
            payload = message.get("bytes")
            assert isinstance(payload, bytes)
        received.append(payload)
        await send({"type": "websocket.close"})

    async with WebSocketSession(app) as session:
        await session.connect()
        fragment = "A" * 512 if opcode is Opcode.TEXT else b"A" * 512
        await session.client.send_fragments([fragment] * 6)
        await session.client.wait_closed()

    expected = "A" * 512 * 6 if opcode is Opcode.TEXT else b"A" * 512 * 6
    assert received == [expected]


async def test_server_reject_connection():
    disconnected_message = {}

    async def app(scope, receive, send):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"

        message = await receive()
        assert message["type"] == "websocket.connect"

        await send({"type": "websocket.close"})
        disconnected_message = await receive()

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        assert exc_info.value.response.status_code == 403

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


async def test_server_reject_connection_with_response():
    disconnected_message = {}

    async def app(scope, receive, send):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"
        assert "extensions" in scope and "websocket.http.response" in scope["extensions"]

        message = await receive()
        assert message["type"] == "websocket.connect"

        response = Response(b"goodbye", status_code=400)
        await response(scope, receive, send)
        disconnected_message = await receive()

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 400
        assert response.body == b"goodbye"

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


async def test_server_reject_connection_with_custom_content_headers():
    body = b'{"detail":"Unauthorized"}'

    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        await receive()
        response = Response(body, status_code=401, media_type="application/json")
        await response(scope, receive, send)

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 401
        assert response.body == body
        assert response.headers.get_all("Content-Length") == [str(len(body))]
        assert response.headers.get_all("Content-Type") == ["application/json"]


async def test_server_reject_connection_with_non_utf8_body():
    body = b"\x81\xfe\x00\xff invalid utf-8 \xff"

    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        await receive()
        await send(
            {
                "type": "websocket.http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/octet-stream")],
            }
        )
        await send({"type": "websocket.http.response.body", "body": body})

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 400
        assert response.body == body


async def test_server_reject_connection_with_multibody_response():
    disconnected_message = {}

    async def app(scope, receive, send):
        nonlocal disconnected_message
        assert scope["type"] == "websocket"
        assert "extensions" in scope
        assert "websocket.http.response" in scope["extensions"]

        message = await receive()
        assert message["type"] == "websocket.connect"
        await send(
            {
                "type": "websocket.http.response.start",
                "status": 400,
                "headers": [
                    (b"Content-Length", b"20"),
                    (b"Content-Type", b"text/plain"),
                ],
            }
        )
        await send({"type": "websocket.http.response.body", "body": b"x" * 10, "more_body": True})
        await send({"type": "websocket.http.response.body", "body": b"y" * 10})
        disconnected_message = await receive()

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 400
        assert response.body == (b"x" * 10) + (b"y" * 10)

    assert disconnected_message == {"type": "websocket.disconnect", "code": 1006}


async def test_server_reject_connection_with_invalid_status():
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        assert "extensions" in scope and "websocket.http.response" in scope["extensions"]

        message = await receive()
        assert message["type"] == "websocket.connect"

        await send(
            {
                "type": "websocket.http.response.start",
                "status": 700,
                "headers": [(b"Content-Length", b"0"), (b"Content-Type", b"text/plain")],
            }
        )

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 500
        assert response.body == b"Internal Server Error"
        assert response.headers["content-length"] == "21"
        assert response.headers["connection"] == "close"


async def test_server_reject_connection_with_body_nolength():
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"
        assert "extensions" in scope
        assert "websocket.http.response" in scope["extensions"]

        message = await receive()
        assert message["type"] == "websocket.connect"

        await send({"type": "websocket.http.response.start", "status": 403, "headers": []})
        await send({"type": "websocket.http.response.body", "body": b"hardbody"})

    async with WebSocketSession(app) as session:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await session.connect()
        response = exc_info.value.response
        assert response.status_code == 403
        assert response.body == b"hardbody"
        assert response.headers["content-length"] == "8"


async def test_server_can_read_messages_in_buffer_after_close():
    frames = []
    disconnect_message = {}

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send({"type": "websocket.accept"})
            # the client's frames and its close land before the app reads any of them
            await tonio.sleep(0.2)

        async def websocket_disconnect(self, message):
            nonlocal disconnect_message
            disconnect_message = message

        async def websocket_receive(self, message):
            _bytes = message.get("bytes")
            assert _bytes is not None
            frames.append(_bytes)

    async with WebSocketSession(App) as session:
        await session.connect()
        await session.client.send(b"abc")
        await session.client.send(b"abc")
        await session.client.send(b"abc")
        await session.client.close()

    assert frames == [b"abc", b"abc", b"abc"]
    assert disconnect_message == {"type": "websocket.disconnect", "code": 1000, "reason": ""}


async def test_shutdown_waits_for_app_task_to_complete(unused_tcp_port):
    app_completed = tonio.Event()

    async def app(scope, receive, send):
        message = await receive()
        assert message["type"] == "websocket.connect"
        await send({"type": "websocket.accept"})
        message = await receive()
        assert message["type"] == "websocket.disconnect"
        await tonio.sleep(0.3)
        app_completed.set()

    config = Config(app=app, lifespan="off", port=unused_tcp_port)
    async with run_server(config):
        async with WebSocketSession(port=unused_tcp_port) as session:
            await session.connect()
            await session.client.close()
        # the client is gone: only the app task is left running
        await tonio.sleep(0.1)
    assert app_completed.is_set()


async def test_default_server_headers():
    async with WebSocketSession(AcceptApp) as session:
        response = await session.connect()
        assert response.headers.get("server") == "punkasgi"
        assert len(response.headers.get_all("date")) == 1


async def test_no_server_headers():
    async with WebSocketSession(AcceptApp, server_header=False) as session:
        response = await session.connect()
        assert "server" not in response.headers


async def test_multiple_server_header():
    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            await self.send(
                {
                    "type": "websocket.accept",
                    "headers": [
                        (b"Server", b"over-ridden"),
                        (b"Server", b"another-value"),
                    ],
                }
            )

    async with WebSocketSession(App) as session:
        response = await session.connect()
        assert response.headers.get_all("Server") == ["punkasgi", "over-ridden", "another-value"]


async def test_lifespan_state(unused_tcp_port):
    expected_states = [{"a": 123, "b": [1]}, {"a": 123, "b": [1, 2]}]
    actual_states = []

    async def lifespan_app(scope, receive, send):
        message = await receive()
        assert message["type"] == "lifespan.startup" and "state" in scope
        scope["state"]["a"] = 123
        scope["state"]["b"] = [1]
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.complete"})

    class App(WebSocketResponse):
        async def websocket_connect(self, message):
            assert "state" in self.scope
            actual_states.append(deepcopy(self.scope["state"]))
            self.scope["state"]["a"] = 456
            self.scope["state"]["b"].append(2)
            await self.send({"type": "websocket.accept"})

    async def app_wrapper(scope, receive, send):
        if scope["type"] == "lifespan":
            return await lifespan_app(scope, receive, send)
        return await App(scope, receive, send)

    config = Config(app=app_wrapper, lifespan="on", port=unused_tcp_port)
    async with run_server(config):
        for _ in range(2):
            async with WebSocketSession(port=unused_tcp_port) as session:
                response = await session.connect()
                assert response.status_code == 101

    assert expected_states == actual_states


async def test_server_keepalive_ping_pong():
    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                break

    async with WebSocketSession(app, ws_ping_interval=0.1, ws_ping_timeout=5.0) as session:
        await session.connect()
        connection = session.connection

        async def pump():
            # the client answers pings on the fly; it also has to drive its own reads to do so
            while not connection.transport_closed:
                try:
                    await session.client.recv()
                except Exception:
                    return

        tonio.spawn.without_tracking(pump())
        for _ in range(100):
            if connection.ping_sent_at != 0.0:
                break
            await tonio.sleep(0.05)
        assert connection.ping_sent_at != 0.0
        await tonio.sleep(0.2)
        assert not connection.transport_closed


async def test_server_keepalive_ping_timeout():
    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.disconnect":
                break

    async with WebSocketSession(app, ws_ping_interval=0.1, ws_ping_timeout=0.1, log_level="trace") as session:
        await session.connect()
        # swallow the pong replies so the server's ping never gets answered
        session.client.mute = True
        with pytest.raises(websockets.exceptions.ConnectionClosedError) as exc_info:
            await session.client.recv()
        assert exc_info.value.rcvd is not None
        assert exc_info.value.rcvd.code == 1011
        assert exc_info.value.rcvd.reason == "keepalive ping timeout"


async def test_server_keepalive_disabled():
    async with WebSocketSession(AcceptApp, ws_ping_interval=None) as session:
        await session.connect()
        await tonio.sleep(0.1)
        assert session.connection.ping_sent_at == 0.0


async def test_close_waits_for_the_peer_close_frame():
    """A server close leaves the transport open until the peer echoes it (RFC 6455 5.5.1)."""
    finished = tonio.Event()
    async with WebSocketSession(wrap_finished(accept_then_close_app, finished)) as session:
        await session.connect()
        await finished.wait()
        connection = session.connection
        assert not connection.transport_closed

        # reading the server's close makes the client echo it
        await session.client.wait_closed()
        await session.finished()
        assert connection.transport_closed
        assert session.client.close_code == 1000


async def test_data_frame_and_peer_close_frame_in_one_read():
    """A peer close frame is processed even when preceded by data in the same read."""
    finished = tonio.Event()
    async with WebSocketSession(wrap_finished(accept_then_close_app, finished)) as session:
        await session.connect()
        await finished.wait()
        connection = session.connection

        client = session.client
        client.protocol.send_text(b"x")
        client.protocol.send_close(1000)
        await client.stream.send_all(b"".join(client.protocol.data_to_send()))
        await session.finished()
        assert connection.transport_closed


async def test_ping_while_closing():
    """A ping crossing the server close cannot break the closing handshake."""
    finished = tonio.Event()
    async with WebSocketSession(wrap_finished(accept_then_close_app, finished)) as session:
        await session.connect()
        await finished.wait()
        connection = session.connection

        await session.client.ping()
        await tonio.sleep(0.05)
        assert not connection.transport_closed

        await session.client.wait_closed()
        await session.finished()
        assert connection.transport_closed


async def test_close_gives_up_when_the_peer_never_replies(monkeypatch):
    """A peer that never echoes the close frame cannot keep the connection (RFC 6455 7.1.1)."""
    monkeypatch.setattr(WebSocketConnection, "close_timeout", 0)
    finished = tonio.Event()
    async with WebSocketSession(wrap_finished(accept_then_close_app, finished)) as session:
        await session.connect()
        connection = session.connection
        await finished.wait()
        await session.finished()
        assert connection.transport_closed


async def test_shutdown_while_the_close_reply_is_pending():
    """Server shutdown does not send a second close frame during the handshake."""
    finished = tonio.Event()
    async with WebSocketSession(wrap_finished(accept_then_close_app, finished)) as session:
        await session.connect()
        await finished.wait()
        connection = session.connection
        assert not connection.transport_closed

        await connection.shutdown()
        assert connection.transport_closed
        await session.finished()
        await session.client.wait_closed()
        assert session.client.close_code == 1000


async def test_send_after_peer_close_raises_client_disconnected():
    accepted = tonio.Event()
    send_failed = tonio.Event()

    async def app(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        accepted.set()
        message = await receive()
        assert message["type"] == "websocket.disconnect"
        try:
            await send({"type": "websocket.send", "text": "x"})
        except OSError:
            send_failed.set()

    async with WebSocketSession(app) as session:
        await session.connect()
        await accepted.wait()
        await session.client.close()
        await send_failed.wait()
