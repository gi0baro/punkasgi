# punkasgi benchmarks

{{ include './_helpers.tpl' }}

Run at: {{ =datetime.datetime.fromtimestamp(data.run_at).strftime('%a %d %b %Y, %H:%M') }}    
Environment: {{ =benv }} (CPUs: {{ =data.cpu }})    
CPython 3.14 free-threaded   
punkasgi {{ =data.versions.punkasgi }} (tonio {{ =data.versions.tonio }}, httpunk {{ =data.versions.httpunk }})   
Granian {{ =data.versions.granian }}   
Uvicorn {{ =data.versions.uvicorn }}    

### Methodology

Every server serves the same ASGI application and is run with 2, 4 and 8 threads or
workers: punkasgi with `--threads N` (a single process), Granian with `--workers N` and
`--runtime-threads 1`, Uvicorn with `--workers N`. Granian and Uvicorn use the plain
`asyncio` event loop. WebSockets are disabled unless the section says otherwise.

Tests are performed with `oha` for 10 seconds at a concurrency growing with the
threads / workers (the concurrency stated in each row), preceded by a primer run at
concurrency 8 for 4 seconds and a warmup run at the row's concurrency for 3 seconds.

The *get* benchmark is an HTTP GET request returning a 10KB plain-text response (a single
static byte string). The *echo* benchmark is an HTTP POST request with a 10KB plain-text
body, streamed back in the chunks the server delivers it in.

### HTTP/1.1

#### get 10KB

{{ _data = data.results["http1"] }}
{{ _bench = "get 10KB" }}
{{ include './_table.tpl' }}

#### echo 10KB (iter)

{{ _bench = "echo 10KB (iter)" }}
{{ include './_table.tpl' }}

### HTTP/2

punkasgi is run with `--http h2`, Granian with `--http 2` and `--runtime-threads 2`,
Uvicorn with `--http zttp --http2`; the client uses HTTP/2 prior knowledge over plain TCP.

#### get 10KB

{{ _data = data.results["http2"] }}
{{ _bench = "get 10KB" }}
{{ include './_table.tpl' }}

#### echo 10KB (iter)

{{ _bench = "echo 10KB (iter)" }}
{{ include './_table.tpl' }}

### Files

An HTTP GET request returning a ~50KB JPEG image, read in full and returned as a single
byte string.

{{ _data = data.results["files"] }}
{{ _bench = "files" }}
{{ include './_table.tpl' }}

### Long I/O

Plain-text responses after a simulated I/O wait of 10ms.

{{ _data = data.results["io"] }}
{{ _bench = "10ms" }}
{{ include './_table.tpl' }}

### WebSockets

Broadcasting: concurrent clients each send a fixed number of messages and receive the
messages of every connected client. Messages are 1 KB JSON text frames, no compression
(not every server negotiates permessage-deflate). Throughput is in messages per second.
Broadcasting needs every client in the same process, so only punkasgi scales its threads:
Granian (with `--runtime-threads 2`) and Uvicorn run a single worker.

{{ _data = data.results["ws"] }}
{{ include './_ws_table.tpl' }}

### Resources

CPU time and memory (proportional set size) of the whole server process tree during the
10 seconds measurement run of the *echo* benchmark at 8 threads / workers. CPU is the
aggregate utilisation, where 100% is one core; idle memory is sampled after startup, before
any traffic.

{{ _n = 8 }}
{{ _bench = "echo 10KB (iter)" }}
{{ _sections = [("http1", "HTTP/1.1"), ("http2", "HTTP/2")] }}
{{ include './_resources_table.tpl' }}
