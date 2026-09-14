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
import os
import socket
import ssl
from hashlib import md5
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
import trustme

from punkasgi.config import LOGGING_CONFIG


# pytest's caplog cannot capture a non-propagating logger, and Config.configure_logging
# rebuilds the handlers, so the default config propagates for the whole suite
LOGGING_CONFIG["loggers"]["punkasgi"]["propagate"] = True


@pytest.fixture
def tls_certificate_authority():
    return trustme.CA()


@pytest.fixture
def tls_certificate(tls_certificate_authority):
    return tls_certificate_authority.issue_cert("localhost", "127.0.0.1", "::1")


@pytest.fixture
def tls_certificate_private_key_path(tls_certificate):
    with tls_certificate.private_key_pem.tempfile() as private_key:
        yield private_key


@pytest.fixture
def tls_certificate_server_cert_path(tls_certificate):
    with tls_certificate.cert_chain_pems[0].tempfile() as cert_pem:
        yield cert_pem


@pytest.fixture
def tls_ca_ssl_context(tls_certificate_authority):
    ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    tls_certificate_authority.configure_trust(ssl_ctx)
    return ssl_ctx


@pytest.fixture
def short_socket_name(tmp_path, tmp_path_factory):
    max_sock_len = 100
    socket_filename = "my.sock"
    identifier = f"{uuid4()}-"
    identifier_len = len(identifier.encode())
    tmp_dir = Path("/tmp").resolve()
    os_tmp_dir = Path(os.getenv("TMPDIR", "/tmp")).resolve()
    basetemp = Path(str(tmp_path_factory.getbasetemp())).resolve()
    hash_basetemp = md5(str(basetemp).encode()).hexdigest()

    def make_tmp_dir(base_dir):
        return TemporaryDirectory(dir=str(base_dir), prefix="p-", suffix=f"-{hash_basetemp}")

    paths = basetemp, os_tmp_dir, tmp_dir
    for tmp_dir_path in paths:
        with make_tmp_dir(tmp_dir_path) as tmpd:
            tmpd = Path(tmpd).resolve()
            sock_path = str(tmpd / socket_filename)
            sock_path_len = len(sock_path.encode())
            if sock_path_len <= max_sock_len:
                if max_sock_len - sock_path_len >= identifier_len:
                    sock_path = str(tmpd / "".join((identifier, socket_filename)))
                yield sock_path
                return


def _unused_port(socket_type):
    with contextlib.closing(socket.socket(type=socket_type)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def unused_tcp_port():
    return _unused_port(socket.SOCK_STREAM)
