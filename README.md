# punkasgi

punkasgi is an ASGI server for the [TonIO](https://github.com/gi0baro/tonio) runtime,
built on top of [HTTPunk](https://github.com/gi0baro/httpunk).

> **Warning:** punkasgi is in an early stage and still work in progress.

> **Note:** punkasgi was built with substantial help from LLMs, under human supervision.

## In a nutshell

- HTTP/1.0, HTTP/1.1 and HTTP/2 (prior knowledge on plain TCP, ALPN over TLS), with
  every protocol behaviour coming from httpunk: keep-alive, head timeouts, framing,
  `Date` headers, graceful shutdown
- WebSockets over HTTP/1.1 through the sans-io `websockets` implementation, with
  keepalive pings, per-message deflate and the `websocket.http.response` extension
- The ASGI 3 protocol handling (scope contents, `receive()` / `send()` semantics, lifespan,
  websocket messages) follows [uvicorn](https://github.com/Kludex/uvicorn)
- Single process architecture: the TonIO runtime's threads are the workers

## Installation

```shell
pip install punkasgi
```

punkasgi needs a free-threaded CPython 3.14 or later, as tonio does. The `standard` extra
adds `python-dotenv` (for `--env-file`) and `PyYAML` (for YAML logging configurations).

## Quickstart

```python
# main.py
async def app(scope, receive, send):
    assert scope["type"] == "http"
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"Hello, world!"})
```

```shell
punkasgi main:app
```

Or *programmatically*:

```python
import punkasgi

punkasgi.run("main:app", host="0.0.0.0", port=8000, threads=4)
```

`punkasgi --help` lists every option. The ones worth knowing:

| option | note |
|---|---|
| `--threads` | size of the tonio runtime, defaults to `$WEB_CONCURRENCY` or the CPU count |
| `--http auto\|h1\|h2` | protocol selection: `auto` sniffs the HTTP/2 preface on plain TCP and follows ALPN over TLS |
| `--ws/--no-ws` | WebSocket upgrades on or off; with them off an upgrade request is answered 400 |
| `--timeout-keep-alive` | hyper's head read timeout: it bounds the idle wait between requests together with the read of the next request head |
| `--timeout-graceful-shutdown` | how long a shutdown waits for in-flight requests; unset waits without a deadline |
| `--proxy-headers` | trust `X-Forwarded-For` / `X-Forwarded-Proto` from `--forwarded-allow-ips`; off by default |
| `--access-log` | one `punkasgi.access` line per response; off by default |

A first `SIGINT` or `SIGTERM` starts a graceful shutdown; a second `SIGINT` leaves at once
with whatever is still in flight. Environment variables use the `PUNKASGI_` prefix (e.g.
`PUNKASGI_PORT`), loggers are `punkasgi.error`, `punkasgi.access` and `punkasgi.asgi`,
and the default `server` header is `punkasgi`.

## Behaviours worth knowing

These follow httpunk, and through it hyper, rather than any other server:

- **Unread request bodies.** After a response completes, a request body the application
  left unread is drained only if it is already buffered; otherwise the connection closes
  instead of being reused for the next request.
- **Response `content-length`.** punkasgi does not check the body against the declared
  length. On HTTP/1 a body shorter than declared fails the response and closes the
  connection, and a longer one is cut at the declared length; on HTTP/2 the frames go out
  as sent.
- **`Date` header.** Always written, on both protocols.

## License

punkasgi is released under the BSD-3-Clause license.
