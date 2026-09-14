import pathlib

import tonio.colored as tonio
from tonio.colored import fs


# single-shot responses declare their length, as any framework does: a response of unknown
# length is a stream (head first, chunked) on every server
def plaintext_start(length):
    return {
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(length).encode())],
    }


STREAM_START = {
    "type": "http.response.start",
    "status": 200,
    "headers": [(b"content-type", b"text/plain; charset=utf-8")],
}
MEDIA_RESPONSE = {
    "type": "http.response.start",
    "status": 200,
    "headers": [(b"content-type", b"image/jpeg"), (b"content-length", b"50486")],
}

BODY_BYTES = {
    10: b"x" * 10,
    1000: b"x" * 1024,
    10_000: b"x" * 1024 * 10,
    100_000: b"x" * 1024 * 100,
}

MEDIA_PATH = pathlib.Path(__file__).parent / "assets" / "media.jpg"


def b_builder(size):
    body = BODY_BYTES[size]
    start = plaintext_start(len(body))

    async def route(scope, receive, send):
        await send(start)
        await send({"type": "http.response.body", "body": body, "more_body": False})

    return route


async def echo(scope, receive, send):
    msg = await receive()
    await send(plaintext_start(len(msg["body"])))
    await send({"type": "http.response.body", "body": msg["body"], "more_body": False})


async def echo_iter(scope, receive, send):
    await send(STREAM_START)
    more_body = True
    while more_body:
        msg = await receive()
        more_body = msg.get("more_body", False)
        await send({"type": "http.response.body", "body": msg.get("body", b""), "more_body": more_body})


async def file_body(scope, receive, send):
    await send(MEDIA_RESPONSE)
    async with await fs.open(MEDIA_PATH, "rb") as f:
        data = await f.read()
    await send({"type": "http.response.body", "body": data, "more_body": False})


def io_builder(wait):
    wait = wait / 1000

    start = plaintext_start(10)

    async def io(scope, receive, send):
        await tonio.sleep(wait)
        await send(start)
        await send({"type": "http.response.body", "body": BODY_BYTES[10], "more_body": False})

    return io


async def handle_404(scope, receive, send):
    content = b"Not found"
    await send(plaintext_start(len(content)))
    await send({"type": "http.response.body", "body": content, "more_body": False})


routes = {
    "/b10": b_builder(10),
    "/b1k": b_builder(1000),
    "/b10k": b_builder(10_000),
    "/b100k": b_builder(100_000),
    "/echo": echo,
    "/echoi": echo_iter,
    "/fb": file_body,
    "/io10": io_builder(10),
    "/io100": io_builder(100),
}


def app(scope, receive, send):
    handler = routes.get(scope["path"], handle_404)
    return handler(scope, receive, send)
