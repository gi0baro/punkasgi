from __future__ import annotations

from contextlib import asynccontextmanager

import tonio.colored as tonio

from punkasgi import Config, Server


@asynccontextmanager
async def run_server(config: Config, sockets=None):
    server = Server(config=config)
    done = tonio.Event()

    async def runner():
        try:
            await server.serve(sockets=sockets)
        finally:
            done.set()

    tonio.spawn.without_tracking(runner())
    await tonio.select(server.started.wait(), done.wait())
    try:
        yield server
    finally:
        server.exit.set()
        await done.wait()
