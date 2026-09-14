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
import os
import platform
import ssl
import sys
from collections.abc import Callable
from configparser import RawConfigParser
from typing import IO, Any

import click

from punkasgi._types import ASGIApplication
from punkasgi._version import __version__
from punkasgi.config import (
    HTTP_PROTOCOLS,
    LIFESPAN,
    LOG_LEVELS,
    LOGGING_CONFIG,
    SSL_PROTOCOL_VERSION,
    STARTUP_FAILURE,
    Config,
    HTTPProtocolType,
    LifespanType,
)
from punkasgi.server import Server


LEVEL_CHOICES = click.Choice(list(LOG_LEVELS.keys()))
LIFESPAN_CHOICES = click.Choice(list(LIFESPAN.keys()))
HTTP_CHOICES = click.Choice(HTTP_PROTOCOLS)

logger = logging.getLogger("punkasgi.error")


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(
        "Running punkasgi {version} with {py_implementation} {py_version} on {system}".format(
            version=__version__,
            py_implementation=platform.python_implementation(),
            py_version=platform.python_version(),
            system=platform.system(),
        )
    )
    ctx.exit()


@click.command(context_settings={"auto_envvar_prefix": "PUNKASGI"})
@click.argument("app", envvar="PUNKASGI_APP")
@click.option("--host", type=str, default="127.0.0.1", help="Bind socket to this host.", show_default=True)
@click.option(
    "--port",
    type=int,
    default=8000,
    help="Bind socket to this port. If 0, an available port will be picked.",
    show_default=True,
)
@click.option("--uds", type=str, default=None, help="Bind to a UNIX domain socket.")
@click.option("--fd", type=int, default=None, help="Bind to socket from this file descriptor.")
@click.option(
    "--threads",
    default=None,
    type=int,
    help="Number of runtime threads. Defaults to the $WEB_CONCURRENCY environment variable if available, "
    "or the tonio runtime default (CPU count).",
)
@click.option("--http", type=HTTP_CHOICES, default="auto", help="HTTP protocol version.", show_default=True)
@click.option("--ws/--no-ws", is_flag=True, default=True, help="Enable/Disable WebSocket upgrades.")
@click.option(
    "--ws-max-size", type=int, default=16777216, help="WebSocket max size message in bytes", show_default=True
)
@click.option(
    "--ws-max-queue", type=int, default=32, help="The maximum length of the WebSocket message queue.", show_default=True
)
@click.option(
    "--ws-ping-interval", type=float, default=20.0, help="WebSocket ping interval in seconds.", show_default=True
)
@click.option(
    "--ws-ping-timeout", type=float, default=20.0, help="WebSocket ping timeout in seconds.", show_default=True
)
@click.option(
    "--ws-per-message-deflate",
    type=bool,
    default=True,
    help="WebSocket per-message-deflate compression",
    show_default=True,
)
@click.option("--lifespan", type=LIFESPAN_CHOICES, default="auto", help="Lifespan implementation.", show_default=True)
@click.option(
    "--env-file",
    type=click.Path(exists=True),
    default=None,
    help="Environment configuration file.",
    show_default=True,
)
@click.option(
    "--log-config",
    type=click.Path(exists=True),
    default=None,
    help="Logging configuration file. Supported formats: .ini, .json, .yaml.",
    show_default=True,
)
@click.option("--log-level", type=LEVEL_CHOICES, default=None, help="Log level. [default: info]", show_default=True)
@click.option("--access-log/--no-access-log", is_flag=True, default=False, help="Enable/Disable access log.")
@click.option(
    "--proxy-headers/--no-proxy-headers",
    is_flag=True,
    default=False,
    help="Enable/Disable X-Forwarded-Proto, X-Forwarded-For to populate url scheme and remote address info.",
)
@click.option(
    "--server-header/--no-server-header", is_flag=True, default=True, help="Enable/Disable default Server header."
)
@click.option(
    "--forwarded-allow-ips",
    type=str,
    default=None,
    help="Comma separated list of IP Addresses, IP Networks, or literals "
    "(e.g. UNIX Socket path) to trust with proxy headers. Defaults to the "
    "$FORWARDED_ALLOW_IPS environment variable if available, or '127.0.0.1'. "
    "The literal '*' means trust everything.",
)
@click.option(
    "--root-path",
    type=str,
    default="",
    help="Set the ASGI 'root_path' for applications submounted below a given URL path.",
)
@click.option("--backlog", type=int, default=2048, help="Maximum number of connections to hold in backlog")
@click.option(
    "--timeout-keep-alive",
    type=int,
    default=5,
    help="Close Keep-Alive connections if no new data is received within this timeout (in seconds).",
    show_default=True,
)
@click.option(
    "--timeout-graceful-shutdown",
    type=int,
    default=None,
    help="Maximum number of seconds to wait for graceful shutdown.",
)
@click.option("--ssl-keyfile", type=str, default=None, help="SSL key file", show_default=True)
@click.option("--ssl-certfile", type=str, default=None, help="SSL certificate file", show_default=True)
@click.option("--ssl-keyfile-password", type=str, default=None, help="SSL keyfile password", show_default=True)
@click.option(
    "--ssl-version",
    type=int,
    default=int(SSL_PROTOCOL_VERSION),
    help="SSL version to use (see stdlib ssl module's)",
    show_default=True,
)
@click.option(
    "--ssl-cert-reqs",
    type=int,
    default=int(ssl.CERT_NONE),
    help="Whether client certificate is required (see stdlib ssl module's)",
    show_default=True,
)
@click.option("--ssl-ca-certs", type=str, default=None, help="CA certificates file", show_default=True)
@click.option(
    "--ssl-ciphers",
    type=str,
    default=None,
    help="Ciphers to use (see stdlib ssl module's). Defaults to OpenSSL's safe defaults.",
    show_default=True,
)
@click.option(
    "--header", "headers", multiple=True, help="Specify custom default HTTP response headers as a Name:Value pair"
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
    help="Display the punkasgi version and exit.",
)
@click.option(
    "--app-dir",
    default="",
    show_default=True,
    help="Look for APP in the specified directory, by adding this to the PYTHONPATH."
    " Defaults to the current working directory.",
)
@click.option(
    "--factory",
    is_flag=True,
    default=False,
    help="Treat APP as an application factory, i.e. a () -> <ASGI app> callable.",
    show_default=True,
)
def main(
    app: str,
    host: str,
    port: int,
    uds: str,
    fd: int,
    threads: int,
    http: HTTPProtocolType,
    ws: bool,
    ws_max_size: int,
    ws_max_queue: int,
    ws_ping_interval: float,
    ws_ping_timeout: float,
    ws_per_message_deflate: bool,
    lifespan: LifespanType,
    env_file: str,
    log_config: str,
    log_level: str,
    access_log: bool,
    proxy_headers: bool,
    server_header: bool,
    forwarded_allow_ips: str,
    root_path: str,
    backlog: int,
    timeout_keep_alive: int,
    timeout_graceful_shutdown: int | None,
    ssl_keyfile: str,
    ssl_certfile: str,
    ssl_keyfile_password: str,
    ssl_version: int,
    ssl_cert_reqs: int,
    ssl_ca_certs: str,
    ssl_ciphers: str | None,
    headers: list[str],
    app_dir: str,
    factory: bool,
) -> None:
    run(
        app,
        host=host,
        port=port,
        uds=uds,
        fd=fd,
        threads=threads,
        http=http,
        ws=ws,
        ws_max_size=ws_max_size,
        ws_max_queue=ws_max_queue,
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_per_message_deflate=ws_per_message_deflate,
        lifespan=lifespan,
        env_file=env_file,
        log_config=LOGGING_CONFIG if log_config is None else log_config,
        log_level=log_level,
        access_log=access_log,
        proxy_headers=proxy_headers,
        server_header=server_header,
        forwarded_allow_ips=forwarded_allow_ips,
        root_path=root_path,
        backlog=backlog,
        timeout_keep_alive=timeout_keep_alive,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_keyfile_password=ssl_keyfile_password,
        ssl_version=ssl_version,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_ciphers=ssl_ciphers,
        headers=[header.split(":", 1) for header in headers],
        factory=factory,
        app_dir=app_dir,
    )


def run(
    app: ASGIApplication | Callable[..., Any] | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    uds: str | None = None,
    fd: int | None = None,
    threads: int | None = None,
    http: HTTPProtocolType = "auto",
    ws: bool = True,
    ws_max_size: int = 16777216,
    ws_max_queue: int = 32,
    ws_ping_interval: float | None = 20.0,
    ws_ping_timeout: float | None = 20.0,
    ws_per_message_deflate: bool = True,
    lifespan: LifespanType = "auto",
    env_file: str | os.PathLike[str] | None = None,
    log_config: dict[str, Any] | str | os.PathLike[str] | RawConfigParser | IO[Any] | None = LOGGING_CONFIG,
    log_level: str | int | None = None,
    access_log: bool = False,
    proxy_headers: bool = False,
    server_header: bool = True,
    forwarded_allow_ips: list[str] | str | None = None,
    root_path: str = "",
    backlog: int = 2048,
    timeout_keep_alive: int = 5,
    timeout_graceful_shutdown: int | None = None,
    ssl_keyfile: str | os.PathLike[str] | None = None,
    ssl_certfile: str | os.PathLike[str] | None = None,
    ssl_keyfile_password: str | None = None,
    ssl_version: int = SSL_PROTOCOL_VERSION,
    ssl_cert_reqs: int = ssl.CERT_NONE,
    ssl_ca_certs: str | os.PathLike[str] | None = None,
    ssl_ciphers: str | None = None,
    ssl_context_factory: Callable[[Config, Callable[[], ssl.SSLContext]], ssl.SSLContext] | None = None,
    headers: list[tuple[str, str]] | None = None,
    app_dir: str | None = None,
    factory: bool = False,
) -> None:
    if app_dir is not None:
        sys.path.insert(0, app_dir)

    config = Config(
        app,
        host=host,
        port=port,
        uds=uds,
        fd=fd,
        threads=threads,
        http=http,
        ws=ws,
        ws_max_size=ws_max_size,
        ws_max_queue=ws_max_queue,
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_per_message_deflate=ws_per_message_deflate,
        lifespan=lifespan,
        env_file=env_file,
        log_config=log_config,
        log_level=log_level,
        access_log=access_log,
        proxy_headers=proxy_headers,
        server_header=server_header,
        forwarded_allow_ips=forwarded_allow_ips,
        root_path=root_path,
        backlog=backlog,
        timeout_keep_alive=timeout_keep_alive,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        ssl_keyfile_password=ssl_keyfile_password,
        ssl_version=ssl_version,
        ssl_cert_reqs=ssl_cert_reqs,
        ssl_ca_certs=ssl_ca_certs,
        ssl_ciphers=ssl_ciphers,
        ssl_context_factory=ssl_context_factory,
        headers=headers,
        factory=factory,
    )
    config.load_app()

    server = Server(config=config)

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if config.uds and os.path.exists(config.uds):
            os.remove(config.uds)

    if not server.started:
        sys.exit(STARTUP_FAILURE)


if __name__ == "__main__":
    main()
