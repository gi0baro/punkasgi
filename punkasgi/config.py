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

import json
import logging
import logging.config
import os
import ssl
import sys
from collections.abc import Callable
from configparser import RawConfigParser
from typing import IO, Any, Literal

from punkasgi._types import ASGIApplication
from punkasgi.importer import ImportFromStringError, import_from_string
from punkasgi.logging import TRACE_LOG_LEVEL
from punkasgi.middleware.message_logger import MessageLoggerMiddleware
from punkasgi.middleware.proxy_headers import ProxyHeadersMiddleware


HTTPProtocolType = Literal["auto", "h1", "h2"]
LifespanType = Literal["auto", "on", "off"]

LOG_LEVELS: dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE_LOG_LEVEL,
}
HTTP_PROTOCOLS: list[HTTPProtocolType] = ["auto", "h1", "h2"]
LIFESPAN: dict[str, str] = {
    "auto": "punkasgi.lifespan.on:LifespanOn",
    "on": "punkasgi.lifespan.on:LifespanOn",
    "off": "punkasgi.lifespan.off:LifespanOff",
}

SSL_PROTOCOL_VERSION: int = ssl.PROTOCOL_TLS_SERVER

STARTUP_FAILURE = 3

LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(levelname)s: %(message)s"},
        "access": {"format": "%(levelname)s: %(message)s"},
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "punkasgi": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "punkasgi.error": {"level": "INFO"},
        "punkasgi.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

logger = logging.getLogger("punkasgi.error")


def create_ssl_context(certfile, keyfile, password, ssl_version, cert_reqs, ca_certs, ciphers):
    ctx = ssl.SSLContext(ssl_version)
    get_password = (lambda: password) if password else None
    ctx.load_cert_chain(certfile, keyfile, get_password)
    ctx.verify_mode = ssl.VerifyMode(cert_reqs)
    if ca_certs:
        ctx.load_verify_locations(ca_certs)
    if ciphers:
        ctx.set_ciphers(ciphers)
    return ctx


class Config:
    def __init__(
        self,
        app: ASGIApplication | Callable[..., Any] | str,
        host: str = "127.0.0.1",
        port: int = 8000,
        uds: str | None = None,
        fd: int | None = None,
        threads: int | None = None,
        http: HTTPProtocolType = "auto",
        ws: bool = True,
        ws_max_size: int = 16 * 1024 * 1024,
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
        factory: bool = False,
    ):
        self.app = app
        self.host = host
        self.port = port
        self.uds = uds
        self.fd = fd
        self.threads = threads
        self.http = http
        self.ws = ws
        self.ws_max_size = ws_max_size
        self.ws_max_queue = ws_max_queue
        self.ws_ping_interval = ws_ping_interval
        self.ws_ping_timeout = ws_ping_timeout
        self.ws_per_message_deflate = ws_per_message_deflate
        self.lifespan = lifespan
        self.log_config = log_config
        self.log_level = log_level
        self.access_log = access_log
        self.proxy_headers = proxy_headers
        self.server_header = server_header
        self.root_path = root_path
        self.backlog = backlog
        self.timeout_keep_alive = timeout_keep_alive
        self.timeout_graceful_shutdown = timeout_graceful_shutdown
        self.ssl_keyfile = ssl_keyfile
        self.ssl_certfile = ssl_certfile
        self.ssl_keyfile_password = ssl_keyfile_password
        self.ssl_version = ssl_version
        self.ssl_cert_reqs = ssl_cert_reqs
        self.ssl_ca_certs = ssl_ca_certs
        self.ssl_ciphers = ssl_ciphers
        self.ssl_context_factory = ssl_context_factory
        self.headers: list[tuple[str, str]] = headers or []
        self.encoded_headers: list[tuple[bytes, bytes]] = []
        self.factory = factory

        self.loaded = False
        self.configure_logging()

        if env_file is not None:
            from dotenv import load_dotenv

            logger.info("Loading environment from '%s'", env_file)
            load_dotenv(dotenv_path=env_file)

        if threads is None and "WEB_CONCURRENCY" in os.environ:
            self.threads = int(os.environ["WEB_CONCURRENCY"])

        self.forwarded_allow_ips: list[str] | str
        if forwarded_allow_ips is None:
            self.forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
        else:
            self.forwarded_allow_ips = forwarded_allow_ips

    @property
    def is_ssl(self) -> bool:
        return bool(self.ssl_keyfile or self.ssl_certfile or self.ssl_context_factory)

    def configure_logging(self) -> None:
        logging.addLevelName(TRACE_LOG_LEVEL, "TRACE")

        if self.log_config is not None:
            if isinstance(self.log_config, os.PathLike):
                self.log_config = os.fspath(self.log_config)

            if isinstance(self.log_config, dict):
                logging.config.dictConfig(self.log_config)
            elif isinstance(self.log_config, str) and self.log_config.endswith(".json"):
                with open(self.log_config) as file:
                    loaded_config = json.load(file)
                    logging.config.dictConfig(loaded_config)
            elif isinstance(self.log_config, str) and self.log_config.endswith((".yaml", ".yml")):
                try:
                    import yaml
                except ImportError as e:
                    raise ImportError(
                        "Install the PyYAML package or punkasgi[standard] to use `--log-config` with YAML files."
                    ) from e

                with open(self.log_config) as file:
                    loaded_config = yaml.safe_load(file)
                    logging.config.dictConfig(loaded_config)
            else:
                logging.config.fileConfig(self.log_config, disable_existing_loggers=False)

        if self.log_level is not None:
            if isinstance(self.log_level, str):
                log_level = LOG_LEVELS[self.log_level.lower()]
            else:
                log_level = self.log_level
            logging.getLogger("punkasgi.error").setLevel(log_level)
            logging.getLogger("punkasgi.access").setLevel(log_level)
            logging.getLogger("punkasgi.asgi").setLevel(log_level)
        if self.access_log is False:
            logging.getLogger("punkasgi.access").handlers = []
            logging.getLogger("punkasgi.access").propagate = False

    def load_app(self) -> Any:
        try:
            return import_from_string(self.app)
        except ImportFromStringError as exc:
            logger.error("Error loading ASGI app. %s" % exc)
            sys.exit(STARTUP_FAILURE)

    def load(self) -> None:
        assert not self.loaded

        if self.ssl_context_factory is not None:

            def default_factory():
                if not self.ssl_certfile:
                    raise RuntimeError(
                        "`default_ssl_context_factory()` requires `ssl_certfile` to be set on `Config`. "
                        "Either pass `ssl_certfile` (and optionally `ssl_keyfile`) or build the `SSLContext` "
                        "directly inside `ssl_context_factory` without calling the default factory."
                    )
                return create_ssl_context(
                    keyfile=self.ssl_keyfile,
                    certfile=self.ssl_certfile,
                    password=self.ssl_keyfile_password,
                    ssl_version=self.ssl_version,
                    cert_reqs=self.ssl_cert_reqs,
                    ca_certs=self.ssl_ca_certs,
                    ciphers=self.ssl_ciphers,
                )

            context = self.ssl_context_factory(self, default_factory)
            if not isinstance(context, ssl.SSLContext):
                raise TypeError(f"`ssl_context_factory` must return an `ssl.SSLContext`, got {type(context).__name__}")
            self.ssl: ssl.SSLContext | None = context
        elif self.is_ssl:
            assert self.ssl_certfile
            self.ssl = create_ssl_context(
                keyfile=self.ssl_keyfile,
                certfile=self.ssl_certfile,
                password=self.ssl_keyfile_password,
                ssl_version=self.ssl_version,
                cert_reqs=self.ssl_cert_reqs,
                ca_certs=self.ssl_ca_certs,
                ciphers=self.ssl_ciphers,
            )
        else:
            self.ssl = None

        encoded_headers = [(key.lower().encode("latin1"), value.encode("latin1")) for key, value in self.headers]
        self.encoded_headers = (
            [(b"server", b"punkasgi")] + encoded_headers
            if b"server" not in dict(encoded_headers) and self.server_header
            else encoded_headers
        )

        self.root_path_bytes = self.root_path.encode("ascii")
        # logging is configured by now: whether access lines go anywhere is settled for the process
        self.access_logging = logging.getLogger("punkasgi.access").hasHandlers()

        self.lifespan_class = import_from_string(LIFESPAN[self.lifespan])

        self.loaded_app = self.load_app()

        try:
            self.loaded_app = self.loaded_app()
        except TypeError as exc:
            if self.factory:
                logger.error("Error loading ASGI app factory: %s", exc)
                sys.exit(STARTUP_FAILURE)
        else:
            if not self.factory:
                logger.warning(
                    "ASGI app factory detected. Using it, but please consider setting the --factory flag explicitly."
                )

        if logger.getEffectiveLevel() <= TRACE_LOG_LEVEL:
            self.loaded_app = MessageLoggerMiddleware(self.loaded_app)
        if self.proxy_headers:
            self.loaded_app = ProxyHeadersMiddleware(self.loaded_app, trusted_hosts=self.forwarded_allow_ips)

        self.loaded = True
