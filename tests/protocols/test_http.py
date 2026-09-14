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

import logging

import pytest
import tonio.colored as tonio
from httpunk import H1BodyError, StreamResetError, Version

from punkasgi.config import Config
from punkasgi.lifespan.on import LifespanOn
from punkasgi.protocols.http import CLOSE
from tests.fakes import FakeRequest, run_cycle
from tests.response import Response


@pytest.fixture(params=["h1", "h2"])
def proto(request):
    return request.param


def make_request(proto, method="GET", target="/", headers=None, body=(), version=None, **kwargs):
    headers = list(headers or [])
    if proto == "h2":
        return FakeRequest(
            method,
            target,
            headers,
            Version.HTTP_2,
            body,
            authority="example.org",
            scheme="http",
            **kwargs,
        )
    headers.insert(0, (b"host", b"example.org"))
    return FakeRequest(method, target, headers, version or Version.HTTP_11, body, **kwargs)


def assert_aborted(proto, request, result):
    if proto == "h2":
        assert request.reset_called
    else:
        assert result is CLOSE


def client_gone_error(proto):
    if proto == "h2":
        return StreamResetError(1, 8)
    return H1BodyError("unexpected_eof", "connection closed before message completed")


POST_BODY = b'{"hello": "world"}'
UPGRADE_HEADERS = [(b"connection", b"upgrade"), (b"upgrade", b"websocket"), (b"sec-websocket-version", b"13")]


async def test_get_request(proto):
    app = Response("Hello, world", media_type="text/plain")

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 200
    assert (b"content-type", b"text/plain; charset=utf-8") in request.response_headers
    assert request.body == b"Hello, world"
    assert request.response_complete


@pytest.mark.parametrize(
    "char",
    [
        pytest.param("c", id="allow_ascii_letter"),
        pytest.param("\t", id="allow_tab"),
        pytest.param(" ", id="allow_space"),
        pytest.param("µ", id="allow_non_ascii_char"),
    ],
)
async def test_header_value_allowed_characters(proto, char):
    app = Response("Hello, world", media_type="text/plain", headers={"key": f"<{char}>"})

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 200
    assert (b"key", f"<{char}>".encode()) in request.response_headers
    assert request.body == b"Hello, world"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("bad header", id="reject_space"),
        pytest.param("bad\x00header", id="reject_null"),
        pytest.param("bad(header", id="reject_open_paren"),
        pytest.param("bad)header", id="reject_close_paren"),
        pytest.param("bad<header", id="reject_less_than"),
        pytest.param("bad>header", id="reject_greater_than"),
        pytest.param("bad@header", id="reject_at"),
        pytest.param("bad,header", id="reject_comma"),
        pytest.param("bad;header", id="reject_semicolon"),
        pytest.param("bad:header", id="reject_colon"),
        pytest.param("bad[header", id="reject_open_bracket"),
        pytest.param("bad]header", id="reject_close_bracket"),
        pytest.param("bad{header", id="reject_open_brace"),
        pytest.param("bad}header", id="reject_close_brace"),
        pytest.param("bad=header", id="reject_equals"),
        pytest.param('bad"header', id="reject_double_quote"),
        pytest.param("bad\\header", id="reject_backslash"),
        pytest.param("bad\theader", id="reject_tab"),
        pytest.param("bad\x7fheader", id="reject_del"),
    ],
)
async def test_invalid_header_name(proto, name):
    app = Response("Hello, world", media_type="text/plain", headers={name: "value"})

    request = make_request(proto)
    await run_cycle(app, request)
    # the head's map is built at the start message, so the failure lands with nothing on
    # the wire and a 500 can answer
    assert request.status == 500
    assert request.body == b"Internal Server Error"


@pytest.mark.parametrize("path", ["/", "/?foo", "/?foo=bar", "/?foo=bar&baz=1"])
async def test_request_logging(path, proto, caplog):
    caplog.set_level(logging.INFO, logger="punkasgi.access")
    logging.getLogger("punkasgi.access").propagate = True

    app = Response("Hello, world", media_type="text/plain")

    request = make_request(proto, target=path)
    await run_cycle(app, request, log_config=None, access_log=True)
    http_version = "2" if proto == "h2" else "1.1"
    assert f'"GET {path} HTTP/{http_version}" 200' in caplog.records[0].message


async def test_head_request(proto):
    app = Response("Hello, world", media_type="text/plain")

    request = make_request(proto, method="HEAD")
    await run_cycle(app, request)
    assert request.status == 200
    assert request.responded == b"Hello, world"
    assert request.response_complete


async def test_post_request(proto):
    async def app(scope, receive, send):
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            assert message["type"] == "http.request"
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
        response = Response(b"Body: " + body, media_type="text/plain")
        await response(scope, receive, send)

    request = make_request(proto, method="POST", headers=[(b"content-length", b"18")], body=[POST_BODY])
    await run_cycle(app, request)
    assert request.status == 200
    assert request.body == b"Body: " + POST_BODY


async def test_bodyless_request_receive(proto):
    request_message = None

    async def app(scope, receive, send):
        nonlocal request_message
        request_message = await receive()
        response = Response(b"", status_code=204)
        await response(scope, receive, send)

    request = make_request(proto)
    await run_cycle(app, request)
    assert request_message == {"type": "http.request", "body": b"", "more_body": False}


async def test_large_post_request(proto):
    messages = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            messages.append(message)
            if not message.get("more_body", False):
                break
        await Response("Hello, world", media_type="text/plain")(scope, receive, send)

    chunks = [b"x" * 65536, b"x" * 34464]
    request = make_request(proto, method="POST", headers=[(b"content-length", b"100000")], body=chunks)
    await run_cycle(app, request)
    assert messages == [
        {"type": "http.request", "body": chunks[0], "more_body": True},
        {"type": "http.request", "body": chunks[1], "more_body": True},
        {"type": "http.request", "body": b"", "more_body": False},
    ]
    assert request.status == 200


async def test_app_exception(proto):
    async def app(scope, receive, send):
        raise Exception()

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500
    assert request.body == b"Internal Server Error"
    connection_close = (b"connection", b"close") in request.response_headers
    assert connection_close is (proto == "h1")


async def test_exception_during_response(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"1", "more_body": True})
        raise Exception()

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 200
    assert request.stream.reset


async def test_no_response_returned(proto):
    async def app(scope, receive, send): ...

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500
    assert request.body == b"Internal Server Error"


async def test_partial_response_returned(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})

    # no content-length: the head went out at the start message, so only an abort is left
    request = make_request(proto)
    result = await run_cycle(app, request)
    assert request.status == 200
    assert request.stream.reset
    if proto == "h1":
        assert result is CLOSE


async def test_partial_response_returned_with_length(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"5")]})

    # a known length holds the head for the body: nothing reached the wire and a 500 can answer
    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500


async def test_partial_streamed_response_returned(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"1", "more_body": True})

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 200
    assert request.stream.reset


async def test_response_header_splitting(proto):
    app = Response(b"", headers={"key": "value\r\nCookie: smuggled=value"})

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500
    assert not any(b"smuggled" in value for _, value in request.response_headers)


async def test_write_failure_after_head(proto, caplog):
    caplog.set_level(logging.ERROR, logger="punkasgi.error")
    app = Response("Hello, world", media_type="text/plain")

    request = make_request(proto, write_error=OSError("write failed"))
    result = await run_cycle(app, request)
    # the head went out with the failing write: no 500 on top of it, one error logged
    assert request.status == 200
    assert not request.response_complete
    assert_aborted(proto, request, result)
    assert [record.getMessage().strip() for record in caplog.records] == ["Exception in ASGI application"]


async def test_duplicate_start_message(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"5")]})
        await send({"type": "http.response.start", "status": 200})

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500


async def test_event_stream_head_goes_out_at_start(proto):
    started = tonio.Event()

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream"), (b"content-length", b"42")],
            }
        )
        started.set()
        await tonio.sleep(0.05)
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": False})

    request = make_request(proto)
    task = tonio.spawn(run_cycle(app, request))
    await started.wait()
    # the head is on the wire before the first event, whatever the declared length
    assert request.status == 200
    assert request.stream is not None and not request.stream.done
    await task
    assert request.body == b"data: 1\n\n"
    assert request.response_complete


async def test_missing_start_message(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.body", "body": b""})

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 500


async def test_message_after_body_complete(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b""})
        await send({"type": "http.response.body", "body": b""})

    request = make_request(proto)
    result = await run_cycle(app, request)
    assert request.status == 200
    assert request.response_complete
    if proto == "h1":
        assert result is CLOSE


async def test_value_returned(proto):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b""})
        return 123

    request = make_request(proto)
    result = await run_cycle(app, request)
    assert request.status == 200
    assert request.response_complete
    if proto == "h1":
        assert result is CLOSE


async def test_early_disconnect(proto):
    got_disconnect_event = False

    async def app(scope, receive, send):
        nonlocal got_disconnect_event

        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

        got_disconnect_event = True

    request = make_request(
        proto,
        method="POST",
        headers=[(b"content-length", b"18")],
        body=[POST_BODY[:5]],
        body_error=client_gone_error(proto),
    )
    await run_cycle(app, request)
    assert got_disconnect_event
    assert request.status is None


async def test_disconnect_while_waiting(proto):
    got_disconnect_event = False

    async def app(scope, receive, send):
        nonlocal got_disconnect_event

        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

        got_disconnect_event = True

    request = make_request(proto)

    async def leave():
        await tonio.sleep(0.05)
        request.gone.set()

    await tonio.spawn(run_cycle(app, request), leave())
    assert got_disconnect_event
    assert request.status is None


async def test_early_response(proto):
    app = Response("Hello, world", media_type="text/plain")

    request = make_request(proto, method="POST", headers=[(b"content-length", b"18")], body=[POST_BODY])
    await run_cycle(app, request)
    assert request.status == 200
    assert request.response_complete


async def test_read_after_response(proto):
    message_after_response = None

    async def app(scope, receive, send):
        nonlocal message_after_response

        response = Response("Hello, world", media_type="text/plain")
        await response(scope, receive, send)
        message_after_response = await receive()

    request = make_request(proto, method="POST", headers=[(b"content-length", b"18")], body=[POST_BODY])
    await run_cycle(app, request)
    assert request.status == 200
    assert message_after_response == {"type": "http.disconnect"}


@pytest.mark.parametrize(
    "version, expected",
    [(Version.HTTP_10, "1.0"), (Version.HTTP_11, "1.1"), (Version.HTTP_2, "2")],
    ids=["http10", "http11", "http2"],
)
async def test_http_version(version, expected):
    async def app(scope, receive, send):
        assert scope["type"] == "http"
        content = "Version: %s" % scope["http_version"]
        response = Response(content, media_type="text/plain")
        await response(scope, receive, send)

    request = make_request("h2" if version is Version.HTTP_2 else "h1", version=version)
    await run_cycle(app, request)
    assert request.status == 200
    assert request.body == f"Version: {expected}".encode()


async def test_h2_host_from_authority():
    headers = None

    async def app(scope, receive, send):
        nonlocal headers
        headers = scope["headers"]
        await Response("Done")(scope, receive, send)

    request = make_request("h2", headers=[(b"host", b"stale"), (b"x-test", b"1")])
    await run_cycle(app, request)
    assert headers == [(b"host", b"example.org"), (b"x-test", b"1")]


async def test_root_path(proto):
    async def app(scope, receive, send):
        assert scope["type"] == "http"
        root_path = scope.get("root_path", "")
        path = scope["path"]
        response = Response(f"root_path={root_path} path={path}", media_type="text/plain")
        await response(scope, receive, send)

    request = make_request(proto)
    await run_cycle(app, request, root_path="/app")
    assert request.status == 200
    assert request.body == b"root_path=/app path=/app/"


async def test_raw_path(proto):
    async def app(scope, receive, send):
        assert scope["type"] == "http"
        path = scope["path"]
        raw_path = scope.get("raw_path", None)
        assert "/app/one/two" == path
        assert b"/app/one%2Ftwo" == raw_path

        response = Response("Done", media_type="text/plain")
        await response(scope, receive, send)

    request = make_request(proto, target="/one%2Ftwo")
    await run_cycle(app, request, root_path="/app")
    assert request.body == b"Done"


async def test_supported_upgrade_request():
    app = Response("Hello, world", media_type="text/plain")

    request = make_request("h1", headers=UPGRADE_HEADERS, leftover=b"tail")
    result = await run_cycle(app, request)
    assert request.detached
    assert result.request is request
    assert result.leftover == b"tail"
    assert request.status is None


async def test_unsupported_ws_upgrade_request(caplog):
    caplog.set_level(logging.WARNING, logger="punkasgi.error")
    app = Response("Hello, world", media_type="text/plain")

    request = make_request("h1", headers=UPGRADE_HEADERS)
    result = await run_cycle(app, request, ws=False)
    assert not request.detached
    assert request.status == 400
    assert request.body == b"Unsupported upgrade request."
    assert (b"connection", b"close") in request.response_headers
    assert result is CLOSE
    assert "Unsupported upgrade request." in caplog.text


async def test_http2_upgrade_request():
    app = Response("Hello, world", media_type="text/plain")

    request = make_request("h1", headers=[(b"connection", b"upgrade"), (b"upgrade", b"h2c")])
    await run_cycle(app, request)
    assert not request.detached
    assert request.status == 200
    assert request.body == b"Hello, world"


async def test_header_upgrade_is_not_websocket():
    app = Response("Hello, world", media_type="text/plain")

    request = make_request("h1", headers=[(b"connection", b"upgrade"), (b"upgrade", b"not-websocket")])
    await run_cycle(app, request)
    assert not request.detached
    assert request.status == 200
    assert request.body == b"Hello, world"


async def test_scopes(proto):
    scopes = []

    async def app(scope, receive, send):
        scopes.append(scope)
        await Response(b"")(scope, receive, send)

    request = make_request(proto)
    await run_cycle(app, request)
    assert scopes[0].get("asgi") == {"version": "3.0", "spec_version": "2.4"}


async def test_iterator_headers(proto):
    async def app(scope, receive, send):
        headers = iter([(b"x-test-header", b"test value")])
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    request = make_request(proto)
    await run_cycle(app, request)
    assert (b"x-test-header", b"test value") in request.response_headers


async def test_lifespan_state(proto):
    expected_states = [{"a": 123, "b": [1]}, {"a": 123, "b": [1, 2]}]

    async def app(scope, receive, send):
        assert "state" in scope
        expected_state = expected_states.pop(0)
        assert scope["state"] == expected_state
        # modifications to keys are not preserved
        scope["state"]["a"] = 456
        # unless of course the value itself is mutated
        scope["state"]["b"].append(2)
        return await Response("Hi!")(scope, receive, send)

    lifespan = LifespanOn(config=Config(app=app))
    lifespan.state.update({"a": 123, "b": [1]})

    for _ in range(2):
        request = make_request(proto)
        await run_cycle(app, request, lifespan=lifespan)
        assert request.status == 200
        assert request.body == b"Hi!"

    assert not expected_states


async def test_trailers(proto):
    async def app(scope, receive, send):
        assert scope["extensions"] == {"http.response.trailers": {}}
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"trailer", b"x-checksum")],
                "trailers": True,
            }
        )
        await send({"type": "http.response.body", "body": b"data", "more_body": False})
        await send({"type": "http.response.trailers", "headers": [(b"x-checksum", b"1")], "more_trailers": True})
        await send({"type": "http.response.trailers", "headers": [(b"x-other", b"2")], "more_trailers": False})

    headers = [] if proto == "h2" else [(b"te", b"trailers")]
    request = make_request(proto, headers=headers)
    await run_cycle(app, request)
    assert request.status == 200
    assert request.body == b"data"
    assert request.stream.trailers == [(b"x-checksum", b"1"), (b"x-other", b"2")]
    assert request.response_complete


async def test_bodyless_response(proto):
    app = Response(b"", status_code=204)

    request = make_request(proto)
    await run_cycle(app, request)
    assert request.status == 204
    assert request.responded == b""
    assert request.response_complete
