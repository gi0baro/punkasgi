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

import os

import pytest

from punkasgi.config import Config


async def asgi_app(scope, receive, send):
    pass


@pytest.mark.parametrize("http", ["auto", "h1", "h2"])
def test_http_protocol(http):
    config = Config(app=asgi_app, http=http)
    config.load()
    assert config.http == http


@pytest.mark.parametrize("ws", [True, False])
def test_ws(ws):
    config = Config(app=asgi_app, ws=ws)
    config.load()
    assert config.ws is ws


def test_threads(monkeypatch):
    monkeypatch.delitem(os.environ, "WEB_CONCURRENCY", raising=False)
    monkeypatch.setattr(os, "process_cpu_count", lambda: 8)
    assert Config(app=asgi_app).threads == 6
    monkeypatch.setattr(os, "process_cpu_count", lambda: 2)
    assert Config(app=asgi_app).threads == 2
    assert Config(app=asgi_app, threads=4).threads == 4
    assert Config(app=asgi_app, threads=1).threads == 1
    monkeypatch.setitem(os.environ, "WEB_CONCURRENCY", "3")
    assert Config(app=asgi_app).threads == 3
    assert Config(app=asgi_app, threads=4).threads == 4


def test_blocking_threads():
    assert Config(app=asgi_app, threads=4).blocking_threads == 16
