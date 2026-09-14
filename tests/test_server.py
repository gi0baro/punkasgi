"""Integration smokes: a real server on a loopback socket, driven by punkreq and the websocket client."""

from __future__ import annotations

import contextvars
import json
import time

import pytest
import tonio.colored as tonio
from httpunk import Backend
from httpunk.h1.client import H1Connection
from punkreq.tonio import Client
from tonio.colored import net

from punkasgi.config import Config
from tests.utils import run_server
from tests.ws import WebSocketSession


async def app(scope, receive, send):
    assert scope["type"] == "http"
    body = scope["path"].encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"%d" % len(body))]})
    await send({"type": "http.response.body", "body": body})


async def test_h1(unused_tcp_port):
    config = Config(app=app, port=unused_tcp_port)
    async with run_server(config):
        async with Client(http2=False) as client:
            response = await client.get(f"http://127.0.0.1:{unused_tcp_port}/hello")
            assert response.status_code == 200
            assert response.http_version == "HTTP/1.1"
            assert await response.read() == b"/hello"
            assert response.headers["server"] == "punkasgi"
            assert response.headers["date"]


async def test_h2_prior_knowledge(unused_tcp_port):
    seen = []

    async def h2_app(scope, receive, send):
        seen.append((scope["http_version"], scope["scheme"], dict(scope["headers"])[b"host"]))
        await app(scope, receive, send)

    config = Config(app=h2_app, port=unused_tcp_port)
    async with run_server(config):
        async with Client(http1=False) as client:
            base = f"http://127.0.0.1:{unused_tcp_port}"
            first, second = await tonio.spawn(client.get(f"{base}/a"), client.get(f"{base}/b"))
            assert first.http_version == "HTTP/2"
            assert {await first.read(), await second.read()} == {b"/a", b"/b"}
    assert seen[0] == ("2", "http", f"127.0.0.1:{unused_tcp_port}".encode())


@pytest.mark.parametrize("http_version", ["HTTP/1.1", "HTTP/2"])
async def test_tls_alpn(
    tls_ca_ssl_context,
    tls_certificate_server_cert_path,
    tls_certificate_private_key_path,
    unused_tcp_port,
    http_version,
):
    config = Config(
        app=app,
        ssl_keyfile=tls_certificate_private_key_path,
        ssl_certfile=tls_certificate_server_cert_path,
        port=unused_tcp_port,
    )
    async with run_server(config):
        async with Client(verify=tls_ca_ssl_context, http2=http_version == "HTTP/2") as client:
            response = await client.get(f"https://127.0.0.1:{unused_tcp_port}/tls")
            assert response.status_code == 200
            assert response.http_version == http_version
            assert await response.read() == b"/tls"


async def test_websocket_round_trip(unused_tcp_port):
    async def ws_app(scope, receive, send):
        assert scope["type"] == "websocket"
        while True:
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
            elif message["type"] == "websocket.receive":
                await send({"type": "websocket.send", "text": message["text"][::-1]})
            elif message["type"] == "websocket.disconnect":
                break

    config = Config(app=ws_app, port=unused_tcp_port)
    async with run_server(config):
        async with WebSocketSession(port=unused_tcp_port) as session:
            response = await session.connect()
            assert response.status_code == 101
            await session.client.send("abc")
            assert await session.client.recv() == "cba"
            await session.client.close()
            assert session.client.close_code == 1000


async def test_uds(short_socket_name):
    config = Config(app=app, uds=short_socket_name)
    async with run_server(config):
        stream = await net.open_unix_socket(short_socket_name)
        async with H1Connection(stream, backend=Backend.tonio) as connection:
            response = await connection.request("GET", "/uds", headers={"host": "localhost"})
            assert response.status == 200
            assert await response.read() == b"/uds"


async def test_shutdown_during_request(unused_tcp_port):
    started = tonio.Event()

    async def slow_app(scope, receive, send):
        started.set()
        await tonio.sleep(0.3)
        await app(scope, receive, send)

    config = Config(app=slow_app, port=unused_tcp_port, lifespan="off", timeout_graceful_shutdown=5)
    async with run_server(config) as server:
        async with Client() as client:

            async def trip():
                await started.wait()
                server.exit.set()

            response, _ = await tonio.spawn(client.get(f"http://127.0.0.1:{unused_tcp_port}"), trip())
            assert response.status_code == 200


async def test_shutdown_during_idle(unused_tcp_port):
    config = Config(app=app, port=unused_tcp_port, timeout_keep_alive=30, timeout_graceful_shutdown=30)
    client = Client()
    async with run_server(config):
        response = await client.get(f"http://127.0.0.1:{unused_tcp_port}")
        assert response.status_code == 200
        started = time.monotonic()
    # the idle keep-alive connection is released by the graceful shutdown, not by the keep-alive timeout
    assert time.monotonic() - started < 2.0
    await client.close()


async def test_contextvars_isolated_between_requests(unused_tcp_port):
    ctx = contextvars.ContextVar("ctx")

    async def ctx_app(scope, receive, send):
        seen = ctx.get("MISSING")
        ctx.set(scope["path"])
        body = json.dumps({"ctx": seen}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", b"%d" % len(body))]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    config = Config(app=ctx_app, port=unused_tcp_port)
    async with run_server(config):
        async with Client() as client:
            for path in ("/first", "/second"):
                response = await client.get(f"http://127.0.0.1:{unused_tcp_port}{path}")
                assert await response.json() == {"ctx": "MISSING"}
