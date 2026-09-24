from __future__ import annotations

import contextlib
import functools
import logging
import os
import signal
import socket
import sys
import threading

import tonio.colored as tonio
from httpunk import Backend, HTTPunkError
from httpunk.h2.server import H2Server
from httpunk.util import GracefulShutdown
from httpunk.util.auto import Builder, SniffCancelledError
from tonio.colored import net, signals

from punkasgi._version import __version__
from punkasgi.config import STARTUP_FAILURE, Config
from punkasgi.logging import TRACE_LOG_LEVEL
from punkasgi.protocols import http, websockets
from punkasgi.protocols.utils import get_local_addr, get_remote_addr


HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)

logger = logging.getLogger("punkasgi.error")


class _Inflight:
    """Per-connection join for HTTP/2 stream handlers.

    Handlers are spawned untracked (a tonio scope keeps a record for every child it ever
    spawned until it exits, unbounded on a long-lived connection), so this is what the
    connection loop waits on before the transport is closed. Every transition is under
    one threading lock, so the drained event is set exactly once: by the last handler to
    leave after the loop stopped accepting.
    """

    __slots__ = ("_lock", "_count", "_closing", "_drained")

    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0
        self._closing = False
        self._drained = tonio.Event()

    def enter(self):
        with self._lock:
            self._count += 1

    def leave(self):
        with self._lock:
            self._count -= 1
            if self._closing and not self._count:
                self._drained.set()

    async def join(self):
        with self._lock:
            self._closing = True
            if not self._count:
                return
        await self._drained.wait()


class Server:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.started = tonio.Event()
        self.exit = tonio.Event()
        self.force = tonio.Event()
        self.listeners = []
        self.websockets = set()

        self._captured_signals = []
        self._backend = Backend.tonio.create()
        self._ssl_context = None
        self._builders = {}
        self._accepting = None
        self._graceful = None

    def run(self, sockets: list[socket.socket] | None = None) -> None:
        config = self.config
        if not config.loaded:
            config.load()
        # tonio installs its signal handlers through the wakeup fd, a main-thread-only affair
        signals = list(HANDLED_SIGNALS) if threading.current_thread() is threading.main_thread() else []
        try:
            tonio.run(
                self._run(sockets),
                context=True,
                signals=signals,
                threads=config.threads,
                blocking_threadpool_size=config.blocking_threads,
            )
        finally:
            for captured_signal in reversed(self._captured_signals):
                signal.raise_signal(captured_signal)

    async def _run(self, sockets):
        # never joined: it dies with the runtime once `serve()` returns
        tonio.spawn.without_tracking(self._watch_signals())
        await self.serve(sockets)

    async def _watch_signals(self):
        with signals.signal_receiver(*HANDLED_SIGNALS) as receiver:
            async for sig in receiver:
                self._captured_signals.append(sig)
                self.exit.set()
                break
            async for sig in receiver:
                self._captured_signals.append(sig)
                if sig == signal.SIGINT:
                    self.force.set()
                    break

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        process_id = os.getpid()

        config = self.config
        if not config.loaded:
            config.load()

        self.lifespan = config.lifespan_class(config)
        self._graceful = GracefulShutdown(Backend.tonio)

        logger.info("punkasgi %s", __version__)
        logger.info("Started server process [%d]", process_id)

        await self.startup(sockets=sockets)
        await self.exit.wait()
        await self.shutdown(sockets=sockets)

        logger.info("Finished server process [%d]", process_id)

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await self.lifespan.startup()
        if self.lifespan.should_exit:
            sys.exit(STARTUP_FAILURE)

        config = self.config
        self._ssl_context = config.ssl
        if self._ssl_context is not None:
            self._ssl_context.set_alpn_protocols(
                {"h1": ["http/1.1"], "h2": ["h2"]}.get(config.http, ["h2", "http/1.1"])
            )
        self._builders = {alpn: self._build(alpn) for alpn in (None, "h2", "http/1.1")}

        if sockets is not None:
            for sock in sockets:
                sock.listen(config.backlog)
                self.listeners.append(net.SocketListener(net.socket.SocketType(sock)))
            listener_sockets = sockets

        elif config.fd is not None:
            sock = socket.fromfd(config.fd, socket.AF_UNIX, socket.SOCK_STREAM)
            sock.listen(config.backlog)
            self.listeners.append(net.SocketListener(net.socket.SocketType(sock)))
            listener_sockets = [sock]

        elif config.uds is not None:
            uds_perms = 0o666
            if os.path.exists(config.uds):
                uds_perms = os.stat(config.uds).st_mode
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(config.uds)
                sock.listen(config.backlog)
                os.chmod(config.uds, uds_perms)
            except BaseException:
                sock.close()
                raise
            self.listeners.append(net.SocketListener(net.socket.SocketType(sock)))
            listener_sockets = [sock]

        else:
            try:
                self.listeners = await net.open_tcp_listeners(config.port, host=config.host, backlog=config.backlog)
            except OSError as exc:
                logger.error(exc)
                await self.lifespan.shutdown()
                sys.exit(STARTUP_FAILURE)
            listener_sockets = [listener.socket for listener in self.listeners]

        if sockets is None:
            self._log_started_message(listener_sockets)

        self._accepting = tonio.spawn.without_results(*[self._accept_loop(listener) for listener in self.listeners])
        self.started.set()

    def _build(self, alpn):
        # the serve function is bound here when the protocol is known; only a sniffed
        # connection (auto over plain TCP, or TLS with no ALPN) decides it after the fact
        config = self.config
        builder = Builder(backend=Backend.tonio)
        builder.http1().header_read_timeout(config.timeout_keep_alive)
        if alpn == "h2" or config.http == "h2":
            return builder.http2_only(), self._serve_h2
        if alpn == "http/1.1" or config.http == "h1":
            return builder.http1_only(), self._serve_h1
        return builder, None

    def _log_started_message(self, listeners):
        config = self.config

        if config.fd is not None:
            logger.info("punkasgi running on socket %s (Press CTRL+C to quit)", listeners[0].getsockname())

        elif config.uds is not None:
            logger.info("punkasgi running on unix socket %s (Press CTRL+C to quit)", config.uds)

        else:
            addr_format = "%s://%s:%d"
            host = "0.0.0.0" if config.host is None else config.host
            if ":" in host:
                addr_format = "%s://[%s]:%d"

            port = config.port
            if port == 0:
                port = listeners[0].getsockname()[1]

            protocol_name = "https" if self._ssl_context is not None else "http"
            logger.info(f"punkasgi running on {addr_format} (Press CTRL+C to quit)", protocol_name, host, port)

    async def _accept_loop(self, listener):
        while True:
            try:
                stream = await listener.accept()
            except OSError, ValueError:
                return
            tonio.spawn.without_tracking(self._connection(stream))

    async def _connection(self, stream):
        transport = stream
        alpn = None
        if self._ssl_context is not None:
            transport = net.tls.TLSStream(stream, self._ssl_context, server_side=True, https_compatible=True)
            try:
                await transport.handshake()
            except Exception as exc:
                logger.log(TRACE_LOG_LEVEL, "%s - TLS handshake failed: %r", _peer(stream), exc)
                stream.close()
                return
            alpn = transport._ssl.selected_alpn_protocol()

        info = http.Connection(
            transport, get_local_addr(transport), get_remote_addr(transport), alpn is not None, self.config
        )
        prefix = "%s:%d - " % info.client if info.client else ""
        trace = logger.level <= TRACE_LOG_LEVEL
        if trace:
            logger.log(TRACE_LOG_LEVEL, "%sHTTP connection made", prefix)

        builder, serve = self._builders[alpn]
        try:
            server = await builder.serve_connection(transport, cancel=self.exit)
        except SniffCancelledError:
            return
        except Exception as exc:
            logger.log(TRACE_LOG_LEVEL, "%sHTTP connection failed: %r", prefix, exc)
            self._backend.close_transport(transport)
            return
        if serve is None:
            serve = self._serve_h2 if isinstance(server, H2Server) else self._serve_h1

        try:
            await self._graceful.watch(server, functools.partial(serve, info=info))
        except (HTTPunkError, OSError, tonio.exceptions.ResourceBroken) as exc:
            logger.log(TRACE_LOG_LEVEL, "%sHTTP connection error: %r", prefix, exc)
        except Exception as exc:
            logger.error("Exception in HTTP connection\n", exc_info=exc)
        finally:
            if trace:
                logger.log(TRACE_LOG_LEVEL, "%sHTTP connection lost", prefix)

    async def _serve_h2(self, server, info):
        handle = self._handle_h2
        spawn = tonio.spawn.without_tracking
        inflight = _Inflight()
        async with server:
            try:
                async for request in server:
                    inflight.enter()
                    spawn(handle(request, info, inflight))
            finally:
                # no cancel: when the iterator raises, httpunk has already failed the
                # connection and woken every stream, so handlers unwind on their own.
                # The join awaits in a `finally`, which only works because this task is
                # never cancelled: it is spawned untracked, the graceful watcher awaits
                # it inline, and the runtime drops (not cancels) parked tasks on exit
                await inflight.join()

    async def _serve_h1(self, server, info):
        # what every request on the connection needs, bound once
        config = self.config
        state = self.lifespan.state
        handle = http.handle
        close = http.CLOSE
        spawn = tonio.spawn
        async with server:
            async for request in server:
                # a task per request, as uvicorn: each ASGI call runs in its own context copy
                try:
                    verdict = await spawn(handle(request, config, state, info))
                except ExceptionGroup as group:
                    raise group.exceptions[0] from None
                if verdict is close:
                    break
                if verdict is not None:
                    await websockets.handle(verdict.request, verdict.leftover, config, state, info, self.websockets)
                    break

    async def _handle_h2(self, request, info, inflight):
        try:
            await http.handle(request, self.config, self.lifespan.state, info)
        except Exception as exc:
            logger.error("Exception in HTTP/2 request handler\n", exc_info=exc)
            with contextlib.suppress(Exception):
                await request.reset()
        finally:
            inflight.leave()

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        logger.info("Shutting down")

        for listener in self.listeners:
            with contextlib.suppress(Exception):
                listener.close()
        for sock in sockets or []:
            sock.close()
        self.exit.set()
        await self._accepting

        # a cut wait, by the deadline or a second SIGINT, means leaving with whatever is in flight:
        # the process exit is what closes the connections
        if not self.force.is_set():
            await self._wait_connections()

        if not self.force.is_set():
            await self.lifespan.shutdown()

    async def _wait_connections(self):
        if not self._graceful.count():
            return
        logger.info("Waiting for connections to close. (CTRL+C to force quit)")

        async def drained():
            for websocket in list(self.websockets):
                tonio.spawn.without_tracking(websocket.shutdown())
            await self._graceful.shutdown()
            return True

        async def forced():
            await self.force.wait()
            return False

        seconds = self.config.timeout_graceful_shutdown
        if seconds is None:
            done = await tonio.select(drained(), forced())
        else:
            done, _ = await tonio.time.timeout(tonio.select(drained(), forced()), seconds)
        if not done:
            logger.info("Graceful shutdown cut short, leaving %d connection(s) in flight", self._graceful.count())


def _peer(stream):
    try:
        return "%s:%d" % stream.socket.getpeername()[:2]
    except Exception:
        return ""
