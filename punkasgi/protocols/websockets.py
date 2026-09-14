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

import email.utils
import logging
import random
import struct
import threading
from http import HTTPStatus
from urllib.parse import unquote

import tonio.colored as tonio
from tonio.colored import net, sync
from websockets.datastructures import Headers
from websockets.exceptions import InvalidState
from websockets.extensions.permessage_deflate import ServerPerMessageDeflateFactory
from websockets.frames import Frame, Opcode
from websockets.http11 import Request, Response
from websockets.server import ServerProtocol

from punkasgi._types import ASGIReceiveEvent, ASGISendEvent
from punkasgi.logging import TRACE_LOG_LEVEL
from punkasgi.protocols.utils import ClientDisconnected, get_client_addr, get_path_with_query_string


logger = logging.getLogger("punkasgi.error")


def _status_phrase(status_code):
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""


STATUS_PHRASES = {status_code: _status_phrase(status_code) for status_code in range(100, 600)}

# shared by every scope: an app mutating them is misbehaving
_ASGI = {"version": "3.0", "spec_version": "2.4"}
_EXTENSIONS = {"websocket.http.response": {}}


def _request_bytes(request):
    head = [f"{request.method} {request.target} HTTP/1.1\r\n".encode("latin-1")]
    for name, value in request.headers.raw_items():
        head.append(name + b": " + value + b"\r\n")
    head.append(b"\r\n")
    return b"".join(head)


def _unexpected(expected, message_type):
    return RuntimeError(f"Expected ASGI message {expected} but got '{message_type}'.")


async def handle(request, leftover, config, app_state, conn, registry):
    connection = WebSocketConnection(request, leftover, config, app_state, conn)
    registry.add(connection)
    try:
        await connection.run()
    finally:
        registry.discard(connection)


class WebSocketConnection:
    __slots__ = (
        "_closing",
        "_lock",
        "_peer_closed",
        "_queue_recv",
        "_queue_send",
        "_write_lock",
        "app",
        "app_state",
        "awaiting_close_reply",
        "client",
        "close_sent",
        "conn",
        "default_headers",
        "disconnect",
        "disconnected",
        "frames",
        "frames_text",
        "handshake_complete",
        "initial_bytes",
        "initial_response",
        "last_ping_rtt",
        "pending_ping_payload",
        "ping_interval",
        "ping_sent_at",
        "ping_timeout",
        "response",
        "root_path",
        "root_path_bytes",
        "scheme",
        "scope",
        "server",
        "transport",
        "transport_closed",
    )

    close_timeout = 10.0

    def __init__(self, request, leftover, config, app_state, conn):
        self.app = config.loaded_app
        self.transport = conn.transport
        self.server = conn.server
        self.client = conn.client
        self.scheme = "wss" if conn.tls else "ws"
        self.root_path = config.root_path
        self.root_path_bytes = config.root_path_bytes
        self.app_state = app_state
        self.default_headers = config.encoded_headers
        self.initial_bytes = _request_bytes(request) + leftover

        extensions = []
        if config.ws_per_message_deflate:
            extensions = [
                ServerPerMessageDeflateFactory(
                    server_max_window_bits=12,
                    client_max_window_bits=12,
                    compress_settings={"memLevel": 5},
                )
            ]
        self.conn = ServerProtocol(extensions=extensions, max_size=config.ws_max_size, logger=logger)

        self.handshake_complete = False
        self.close_sent = False
        self.disconnected = False
        self.transport_closed = False
        self.awaiting_close_reply = False
        self.initial_response = None
        self.scope = None

        # messages to the app, FIFO as uvicorn's queue: the reader parks on a full channel
        # when the app is `ws_max_queue` messages behind. The disconnect is the last message
        # and closes the channel, which also wakes a parked reader
        self._queue_send, self._queue_recv = sync.channel.channel(config.ws_max_queue)
        self.disconnect = None
        # the protocol object is mutated by the app's sends and the reader's parse, which may
        # run on different threads and never await: a sync lock around each mutation and the
        # swap of its outgoing bytes, and around the close flag (`_close()` has five callers).
        # The transport write awaits, and four writers share it (the app, the reader's
        # control replies, the keepalive ping, shutdown): a tonio lock
        self._lock = threading.Lock()
        self._write_lock = sync.Lock()
        self._closing = tonio.Event()
        self._peer_closed = tonio.Event()

        self.ping_interval = config.ws_ping_interval
        self.ping_timeout = config.ws_ping_timeout
        self.pending_ping_payload = None
        self.ping_sent_at = 0.0
        self.last_ping_rtt = 0.0

        # the fragments of a message in progress; a single-frame message never touches it
        self.frames = None
        self.frames_text = False

    async def run(self):
        prefix = "%s:%d - " % self.client if self.client else ""
        trace = logger.level <= TRACE_LOG_LEVEL
        if trace:
            logger.log(TRACE_LOG_LEVEL, "%sWebSocket connection made", prefix)
        try:
            await self._run()
        finally:
            self._close()
            if trace:
                logger.log(TRACE_LOG_LEVEL, "%sWebSocket connection lost", prefix)

    async def _run(self):
        self.conn.receive_data(self.initial_bytes)
        if self.conn.parser_exc is not None:
            return
        request = None
        for event in self.conn.events_received():
            if isinstance(event, Request):
                request = event
                break
        if request is None:
            return

        self.response = self.conn.accept(request)
        if self.response.status_code != 101:
            self._claim_close(handshake_complete=True)
            try:
                await self._write(self.conn.send_response, self.response)
            except ClientDisconnected:
                pass
            return

        headers = [(key.encode("ascii"), value.encode("latin-1")) for key, value in request.headers.raw_items()]
        raw_path, _, query_string = request.path.partition("?")
        subprotocols = []
        for header in request.headers.get_all("Sec-WebSocket-Protocol"):
            subprotocols.extend([token.strip() for token in header.split(",")])
        root_path = self.root_path
        self.scope = {
            "type": "websocket",
            "asgi": _ASGI,
            "http_version": "1.1",
            "scheme": self.scheme,
            "server": self.server,
            "client": self.client,
            "root_path": root_path,
            "path": root_path + (raw_path if "%" not in raw_path else unquote(raw_path)),
            "raw_path": self.root_path_bytes + raw_path.encode("ascii"),
            "query_string": query_string.encode("ascii"),
            "headers": headers,
            "subprotocols": subprotocols,
            "state": self.app_state.copy(),
            "extensions": _EXTENSIONS,
        }
        await self._queue_send.send({"type": "websocket.connect"})

        # the scope joins both tasks on exit, cancelled before their first step included
        async with tonio.scope() as tasks:
            tasks.spawn(self.run_reader())
            tasks.spawn(self.run_keepalive())
            try:
                await self.run_asgi()
                if self.awaiting_close_reply and not self.transport_closed:
                    # the close handshake is in flight: give the peer's close frame uvicorn's close_timeout
                    await self._peer_closed.wait(self.close_timeout)
            finally:
                self._close()
                tasks.cancel()

    def _claim_close(self, *, after_handshake=None, handshake_complete=False, awaiting_close_reply=False):
        # the one transition every close path takes: the caller that gets it sends the close
        # frame or the rejection, the others find it taken. `after_handshake` pins the
        # handshake state the caller assumed; the flags are what the caller's path sets
        with self._lock:
            if self.close_sent or (after_handshake is not None and self.handshake_complete is not after_handshake):
                return False
            self.close_sent = True
            if handshake_complete:
                self.handshake_complete = True
            if awaiting_close_reply:
                self.awaiting_close_reply = True
            return True

    def _complete_handshake(self):
        with self._lock:
            if self.close_sent:
                return False
            self.handshake_complete = True
            return True

    def _close(self):
        with self._lock:
            if self.transport_closed:
                return
            self.transport_closed = True
        self._closing.set()
        self._peer_closed.set()
        transport = self.transport
        # a TLS stream's own close is async: the socket under it is closed, no close_notify
        if isinstance(transport, net.tls.TLSStream):
            transport = transport.transport
        transport.close()

    async def _write(self, produce, *args):
        # one protocol mutation and its bytes, in order with every other writer
        async with self._write_lock:
            with self._lock:
                produce(*args)
                out = self.conn.data_to_send()
            if out:
                await self._send_all(out)

    async def _flush(self):
        # bytes the parser queued (a pong, the close reply): the reader's writes, taking the
        # locks in the one order every writer uses (the sync lock inside the tonio lock)
        async with self._write_lock:
            with self._lock:
                out = self.conn.data_to_send()
            if out:
                await self._send_all(out)

    async def _send_all(self, out):
        if self.transport_closed:
            raise ClientDisconnected()
        try:
            await self.transport.send_all(out[0] if len(out) == 1 else b"".join(out))
        except Exception as exc:
            self.disconnected = True
            raise ClientDisconnected() from exc

    def _enqueue_disconnect(self, code, reason=None):
        message = {"type": "websocket.disconnect", "code": code}
        if reason is not None:
            message["reason"] = reason
        with self._lock:
            if self.disconnect is not None:
                return
            self.disconnect = message
        # sent from its own task: the app's own `websocket.close` on a full queue must not
        # park the app behind the queue only it can drain. The close follows the send, so
        # the disconnect is the last message in
        tonio.spawn.without_tracking(self._send_disconnect(message))

    async def _send_disconnect(self, message):
        await self._queue_send.send(message)
        self._queue_send.close()

    async def run_reader(self):
        while not self.transport_closed:
            try:
                data = await self.transport.receive_some()
            except Exception:
                data = b""
            if not data:
                self._connection_lost()
                return
            with self._lock:
                self.conn.receive_data(data)
                events = None if self.conn.parser_exc is not None else self.conn.events_received()
            if events is None:
                await self._handle_parser_exception()
                return
            for event in events:
                if not isinstance(event, Frame):
                    continue
                opcode = event.opcode
                if opcode is Opcode.TEXT or opcode is Opcode.BINARY:
                    if event.fin:
                        await self._deliver(event.data, opcode is Opcode.TEXT)
                    else:
                        self.frames = [event.data]
                        self.frames_text = opcode is Opcode.TEXT
                elif opcode is Opcode.CONT:
                    self.frames.append(event.data)
                    if event.fin:
                        frames, self.frames = self.frames, None
                        await self._deliver(b"".join(frames), self.frames_text)
                elif opcode is Opcode.PING:
                    await self._handle_ping()
                elif opcode is Opcode.PONG:
                    self._handle_pong(event)
                elif opcode is Opcode.CLOSE:
                    await self._handle_close()
                    return

    def _connection_lost(self):
        with self._lock:
            code = 1005 if self.handshake_complete else 1006
            self.handshake_complete = True
        self.disconnected = True
        self._closing.set()
        self._peer_closed.set()
        self._enqueue_disconnect(code)

    async def _deliver(self, data, text):
        if self.close_sent:
            # the app is past `websocket.close`: the message is dropped, reads go on for the close reply
            return
        if text:
            try:
                message = {"type": "websocket.receive", "text": data.decode()}
            except UnicodeDecodeError:
                logger.exception("Invalid UTF-8 sequence received from client.")
                with self._lock:
                    self.conn.send_close(1007)
                await self._handle_parser_exception()
                return
        else:
            message = {"type": "websocket.receive", "bytes": bytes(data)}
        try:
            await self._queue_send.send(message)
        except BrokenPipeError:
            pass  # the disconnect went in meanwhile: the message is dropped, as after `close_sent`

    async def _handle_ping(self):
        try:
            await self._flush()
        except ClientDisconnected:
            pass

    def _handle_pong(self, event):
        with self._lock:
            if self.pending_ping_payload is None or bytes(event.data) != self.pending_ping_payload:
                return
            self.last_ping_rtt = tonio.time.time() - self.ping_sent_at
            self.pending_ping_payload = None

    async def _handle_close(self):
        if self.close_sent:
            # the peer echoed our close frame: the closing handshake is complete
            self._peer_closed.set()
            self._close()
            return
        assert self.conn.close_rcvd is not None
        try:
            await self._flush()
        except ClientDisconnected:
            pass
        self.disconnected = True
        self._enqueue_disconnect(self.conn.close_rcvd.code, self.conn.close_rcvd.reason)
        self._close()

    async def _handle_parser_exception(self):
        assert self.conn.close_sent is not None
        self._claim_close()
        self._closing.set()
        try:
            await self._flush()
        except ClientDisconnected:
            pass
        self._enqueue_disconnect(self.conn.close_sent.code, self.conn.close_sent.reason)
        self._close()

    async def run_keepalive(self):
        if not self.ping_interval or self.ping_interval <= 0:
            return
        while not self._closing.is_set():
            delay = max(0.0, self.ping_interval - self.last_ping_rtt)
            await self._closing.wait(delay)
            if self._closing.is_set():
                return
            if not self.handshake_complete:
                continue
            # a random payload identifies this ping, so stale or unsolicited pongs are ignored
            payload = struct.pack("!I", random.getrandbits(32))
            with self._lock:
                self.pending_ping_payload = payload
                self.ping_sent_at = tonio.time.time()
            try:
                await self._write(self.conn.send_ping, payload)
            except ClientDisconnected:
                return
            if self.ping_timeout is None:
                continue
            await self._closing.wait(self.ping_timeout)
            with self._lock:
                timed_out = self.pending_ping_payload is not None and not self._closing.is_set()
                self.pending_ping_payload = None
            if timed_out:
                await self._keepalive_timeout()
                return

    async def _keepalive_timeout(self):
        if logger.level <= TRACE_LOG_LEVEL:
            prefix = "%s:%d - " % self.client if self.client else ""
            logger.log(TRACE_LOG_LEVEL, "%sWebSocket keepalive ping timeout", prefix)
        if self._claim_close(after_handshake=True):
            self._closing.set()
            try:
                await self._write(self.conn.fail, 1011, "keepalive ping timeout")
            except ClientDisconnected:
                pass
        self._close()

    async def run_asgi(self):
        try:
            result = await self.app(self.scope, self.receive, self.send)
        except ClientDisconnected:
            pass
        except Exception:
            logger.exception("Exception in ASGI application\n")
            await self._send_500_response()
        else:
            if not self.handshake_complete:
                logger.error("ASGI callable returned without completing handshake.")
                await self._send_500_response()
            elif result is not None:
                logger.error("ASGI callable should return None, but returned '%s'.", result)

    async def _send_500_response(self):
        if self.initial_response is not None or not self._claim_close(after_handshake=False):
            return
        response = self.conn.reject(500, "Internal Server Error")
        try:
            await self._write(self.conn.send_response, response)
        except ClientDisconnected:
            pass

    async def shutdown(self):
        self._closing.set()
        if self.transport_closed:
            self._close()
        elif self._claim_close(after_handshake=True, awaiting_close_reply=True):
            # the app runs on its own thread: the frame goes out before the disconnect that
            # lets the app return and close the transport
            try:
                await self._write(self.conn.send_close, 1012)
            except ClientDisconnected:
                self._close()
            self._enqueue_disconnect(1012)
        elif not self.handshake_complete:
            await self._send_500_response()
            self._close()
        else:
            # a close is already in flight from another path
            self._close()

    async def send(self, message: ASGISendEvent) -> None:
        if self.disconnected:
            raise ClientDisconnected()

        message_type = message["type"]

        if self.handshake_complete:
            if self.close_sent:
                raise RuntimeError(f"Unexpected ASGI message '{message_type}', after sending 'websocket.close'.")
            try:
                if message_type == "websocket.send":
                    bytes_data = message.get("bytes")
                    text_data = message.get("text")
                    if bytes_data is not None:
                        await self._write(self.conn.send_binary, bytes_data)
                    elif text_data is not None:
                        await self._write(self.conn.send_text, text_data.encode())

                elif message_type == "websocket.close":
                    if not self.transport_closed:
                        if not self._claim_close(after_handshake=True, awaiting_close_reply=True):
                            raise ClientDisconnected()  # another path is closing the connection
                        code = message.get("code", 1000)
                        reason = message.get("reason", "") or ""
                        self._enqueue_disconnect(code, reason)
                        self._closing.set()
                        await self._write(self.conn.send_close, code, reason)
                else:
                    raise _unexpected("'websocket.send' or 'websocket.close'", message_type)
            except InvalidState:
                raise ClientDisconnected()

        elif self.initial_response is None:
            if message_type == "websocket.accept":
                logger.info(
                    '%s - "WebSocket %s" [accepted]',
                    get_client_addr(self.scope),
                    get_path_with_query_string(self.scope),
                )
                headers = [
                    (name.decode("latin-1").lower(), value.decode("latin-1"))
                    for name, value in (self.default_headers + list(message.get("headers", [])))
                ]
                accepted_subprotocol = message.get("subprotocol")
                if accepted_subprotocol:
                    headers.append(("Sec-WebSocket-Protocol", accepted_subprotocol))
                self.response.headers.update(headers)

                if not self.transport_closed:
                    if not self._complete_handshake():
                        raise ClientDisconnected()  # closed meanwhile (a parser failure, shutdown)
                    await self._write(self.conn.send_response, self.response)

            elif message_type == "websocket.close":
                if not self._claim_close(after_handshake=False, handshake_complete=True):
                    raise ClientDisconnected()
                self._enqueue_disconnect(1006)
                logger.info(
                    '%s - "WebSocket %s" 403',
                    get_client_addr(self.scope),
                    get_path_with_query_string(self.scope),
                )
                response = self.conn.reject(HTTPStatus.FORBIDDEN, "")
                self._closing.set()
                try:
                    await self._write(self.conn.send_response, response)
                finally:
                    self._close()

            elif message_type == "websocket.http.response.start":
                if not (100 <= message["status"] < 600):
                    raise RuntimeError("Invalid HTTP status code '%d' in response." % message["status"])
                logger.info(
                    '%s - "WebSocket %s" %d',
                    get_client_addr(self.scope),
                    get_path_with_query_string(self.scope),
                    message["status"],
                )
                headers = [
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in list(message.get("headers", []))
                ]
                self.initial_response = (message["status"], headers, b"")
            else:
                raise _unexpected(
                    "'websocket.accept', 'websocket.close' or 'websocket.http.response.start'", message_type
                )

        elif message_type == "websocket.http.response.body":
            body = self.initial_response[2] + message["body"]
            self.initial_response = self.initial_response[:2] + (body,)
            if not message.get("more_body", False):
                status_code = self.initial_response[0]
                response_headers = Headers(self.initial_response[1])
                response_headers.setdefault("Date", email.utils.formatdate(usegmt=True))
                response_headers.setdefault("Connection", "close")
                response_headers.setdefault("Content-Length", str(len(body)))
                response_headers.setdefault("Content-Type", "text/plain; charset=utf-8")
                response = Response(status_code, STATUS_PHRASES[status_code], response_headers, body)
                if not self._claim_close(after_handshake=False, handshake_complete=True):
                    raise ClientDisconnected()
                self._enqueue_disconnect(1006)
                self._closing.set()
                try:
                    await self._write(self.conn.send_response, response)
                finally:
                    self._close()
        else:
            raise _unexpected("'websocket.http.response.body'", message_type)

    async def receive(self) -> ASGIReceiveEvent:
        try:
            return await self._queue_recv.receive()
        except BrokenPipeError:
            # drained past the disconnect: the app gets it again rather than a hang
            return self.disconnect
