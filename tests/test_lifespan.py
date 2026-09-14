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

import pytest

from punkasgi.config import Config
from punkasgi.lifespan.off import LifespanOff
from punkasgi.lifespan.on import LifespanOn


async def test_lifespan_on():
    startup_complete = False
    shutdown_complete = False

    async def app(scope, receive, send):
        nonlocal startup_complete, shutdown_complete
        message = await receive()
        assert message["type"] == "lifespan.startup"
        startup_complete = True
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        shutdown_complete = True
        await send({"type": "lifespan.shutdown.complete"})

    config = Config(app=app, lifespan="on")
    lifespan = LifespanOn(config)

    assert not startup_complete
    assert not shutdown_complete
    await lifespan.startup()
    assert startup_complete
    assert not shutdown_complete
    await lifespan.shutdown()
    assert startup_complete
    assert shutdown_complete


async def test_lifespan_off():
    async def app(scope, receive, send):
        pass

    config = Config(app=app, lifespan="off")
    lifespan = LifespanOff(config)

    await lifespan.startup()
    await lifespan.shutdown()


async def test_lifespan_auto():
    startup_complete = False
    shutdown_complete = False

    async def app(scope, receive, send):
        nonlocal startup_complete, shutdown_complete
        message = await receive()
        assert message["type"] == "lifespan.startup"
        startup_complete = True
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        shutdown_complete = True
        await send({"type": "lifespan.shutdown.complete"})

    config = Config(app=app, lifespan="auto")
    lifespan = LifespanOn(config)

    assert not startup_complete
    assert not shutdown_complete
    await lifespan.startup()
    assert startup_complete
    assert not shutdown_complete
    await lifespan.shutdown()
    assert startup_complete
    assert shutdown_complete


async def test_lifespan_auto_with_error():
    async def app(scope, receive, send):
        assert scope["type"] == "http"

    config = Config(app=app, lifespan="auto")
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert lifespan.error_occurred
    assert not lifespan.should_exit
    await lifespan.shutdown()


async def test_lifespan_on_with_error():
    async def app(scope, receive, send):
        if scope["type"] != "http":
            raise RuntimeError()

    config = Config(app=app, lifespan="on")
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert lifespan.error_occurred
    assert lifespan.should_exit
    await lifespan.shutdown()


@pytest.mark.parametrize("mode", ("auto", "on"))
@pytest.mark.parametrize("raise_exception", (True, False))
async def test_lifespan_with_failed_startup(mode, raise_exception, caplog):
    async def app(scope, receive, send):
        message = await receive()
        assert message["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.failed", "message": "the lifespan event failed"})
        if raise_exception:
            raise RuntimeError()

    config = Config(app=app, lifespan=mode)
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert lifespan.startup_failed
    assert lifespan.error_occurred is raise_exception
    assert lifespan.should_exit
    await lifespan.shutdown()

    error_messages = [
        record.message for record in caplog.records if record.name == "punkasgi.error" and record.levelname == "ERROR"
    ]
    assert "the lifespan event failed" in error_messages.pop(0)
    assert "Application startup failed. Exiting." in error_messages.pop(0)


async def test_lifespan_scope_asgi3app():
    async def asgi3app(scope, receive, send):
        assert scope == {
            "type": "lifespan",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "state": {},
        }

    config = Config(app=asgi3app, lifespan="on")
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert not lifespan.startup_failed
    assert not lifespan.error_occurred
    assert not lifespan.should_exit
    await lifespan.shutdown()


@pytest.mark.parametrize("mode", ("auto", "on"))
@pytest.mark.parametrize("raise_exception", (True, False))
async def test_lifespan_with_failed_shutdown(mode, raise_exception, caplog):
    async def app(scope, receive, send):
        message = await receive()
        assert message["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.failed", "message": "the lifespan event failed"})

        if raise_exception:
            raise RuntimeError()

    config = Config(app=app, lifespan=mode)
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert not lifespan.startup_failed
    await lifespan.shutdown()
    assert lifespan.shutdown_failed
    assert lifespan.error_occurred is raise_exception
    assert lifespan.should_exit

    error_messages = [
        record.message for record in caplog.records if record.name == "punkasgi.error" and record.levelname == "ERROR"
    ]
    assert "the lifespan event failed" in error_messages.pop(0)
    assert "Application shutdown failed. Exiting." in error_messages.pop(0)


async def test_lifespan_state():
    async def app(scope, receive, send):
        message = await receive()
        assert message["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})
        scope["state"]["foo"] = 123
        message = await receive()
        assert message["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.complete"})

    config = Config(app=app, lifespan="on")
    lifespan = LifespanOn(config)

    await lifespan.startup()
    assert lifespan.state == {"foo": 123}
    await lifespan.shutdown()
