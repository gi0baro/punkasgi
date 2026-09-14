import tonio.colored as tonio


clients = set()


async def deliver(ws, message):
    try:
        await ws({"type": "websocket.send", "text": message})
    except Exception:
        pass


async def app(scope, receive, send):
    try:
        await send({"type": "websocket.accept"})
        clients.add(send)

        while True:
            msg = await receive()
            if msg["type"] == "websocket.connect":
                continue
            if msg["type"] == "websocket.disconnect":
                break
            await tonio.spawn.without_results(*[deliver(ws, msg["text"]) for ws in list(clients)])

    finally:
        clients.remove(send)
