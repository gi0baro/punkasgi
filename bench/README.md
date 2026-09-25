# punkasgi benchmarks



Run at: Fri 25 Sep 2026, 11:57    
Environment: AMD Ryzen 7 5700X @ Gentoo Linux 6.18.48 (CPUs: 16)    
CPython 3.14 free-threaded   
punkasgi 0.1.2 (tonio 0.10.1, httpunk 0.4.5)   
Granian 2.8.3   
Uvicorn 0.54.0    

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

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 609251 | 60921 | 1.047ms | 1.155ms | 1.247ms |
| punkasgi | 4 | 128 | 994816 | 99457 | 1.281ms | 1.481ms | 1.626ms |
| punkasgi | 8 | 256 | 1496001 | 149554 | 1.699ms | 2.173ms | 3.158ms |
| Granian | 2 | 64 | 1805691 | 180526 | 0.352ms | 0.561ms | 0.796ms |
| Granian | 4 | 128 | 2576529 | 257559 | 0.494ms | 1.001ms | 1.469ms |
| Granian | 8 | 256 | 2558164 | 255750 | 0.995ms | 2.357ms | 3.135ms |
| Uvicorn zttp | 2 | 64 | 732290 | 73207 | 0.871ms | 1.175ms | 1.388ms |
| Uvicorn zttp | 4 | 128 | 1244538 | 124416 | 1.023ms | 1.675ms | 2.203ms |
| Uvicorn zttp | 8 | 256 | 1774419 | 177393 | 1.434ms | 1.987ms | 3.016ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 392032 | 39204 | 1.629ms | 1.828ms | 2.087ms |
| punkasgi | 4 | 128 | 634333 | 63435 | 2.008ms | 2.341ms | 2.49ms |
| punkasgi | 8 | 256 | 1001047 | 100098 | 2.545ms | 3.384ms | 4.994ms |
| Granian | 2 | 64 | 932870 | 93263 | 0.683ms | 1.01ms | 1.394ms |
| Granian | 4 | 128 | 1313015 | 131279 | 0.97ms | 1.87ms | 2.632ms |
| Granian | 8 | 256 | 1289594 | 128925 | 1.973ms | 4.153ms | 5.168ms |
| Uvicorn zttp | 2 | 64 | 567854 | 56785 | 1.124ms | 1.657ms | 1.7ms |
| Uvicorn zttp | 4 | 128 | 979289 | 97904 | 1.302ms | 2.367ms | 2.758ms |
| Uvicorn zttp | 8 | 256 | 1396651 | 139643 | 1.822ms | 3.316ms | 3.88ms |


### HTTP/2

punkasgi is run with `--http h2`, Granian with `--http 2` and `--runtime-threads 2`,
Uvicorn with `--http zttp --http2`; the client uses HTTP/2 prior knowledge over plain TCP.

#### get 10KB

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 697047 | 69710 | 3.665ms | 4.23ms | 4.625ms |
| punkasgi | 4 | 128 | 1128619 | 112852 | 4.505ms | 5.144ms | 5.641ms |
| punkasgi | 8 | 256 | 1606728 | 160661 | 6.306ms | 7.294ms | 9.767ms |
| Granian | 2 | 64 | 2061027 | 206043 | 1.237ms | 1.643ms | 2.169ms |
| Granian | 4 | 128 | 2705754 | 270462 | 1.883ms | 3.974ms | 5.159ms |
| Granian | 8 | 256 | 2579937 | 257897 | 3.941ms | 8.71ms | 11.221ms |
| Uvicorn zttp | 2 | 64 | 540746 | 54121 | 4.722ms | 8.214ms | 9.393ms |
| Uvicorn zttp | 4 | 128 | 987120 | 98804 | 5.152ms | 11.409ms | 13.737ms |
| Uvicorn zttp | 8 | 256 | 1356864 | 135751 | 7.479ms | 11.88ms | 13.424ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 542322 | 54244 | 4.706ms | 5.131ms | 5.484ms |
| punkasgi | 4 | 128 | 896078 | 89611 | 5.692ms | 6.432ms | 7.2ms |
| punkasgi | 8 | 256 | 1276762 | 127684 | 7.947ms | 9.313ms | 11.23ms |
| Granian | 2 | 64 | 976148 | 97607 | 2.612ms | 3.449ms | 3.855ms |
| Granian | 4 | 128 | 1323255 | 132310 | 3.843ms | 6.829ms | 8.726ms |
| Granian | 8 | 256 | 1204388 | 120431 | 8.439ms | 16.09ms | 19.888ms |
| Uvicorn zttp | 2 | 64 | 447317 | 44772 | 5.7ms | 7.162ms | 7.571ms |
| Uvicorn zttp | 4 | 128 | 777048 | 77786 | 6.554ms | 12.685ms | 14.353ms |
| Uvicorn zttp | 8 | 256 | 1047107 | 104765 | 9.658ms | 17.134ms | 18.186ms |


### Files

An HTTP GET request returning a ~50KB JPEG image, read in full and returned as a single
byte string.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 273166 | 27315 | 2.336ms | 2.806ms | 3.01ms |
| punkasgi | 4 | 128 | 405078 | 40514 | 3.149ms | 3.662ms | 3.82ms |
| punkasgi | 8 | 256 | 501254 | 50133 | 5.08ms | 7.505ms | 7.98ms |
| Granian | 2 | 64 | 901399 | 90132 | 0.707ms | 1.029ms | 1.197ms |
| Granian | 4 | 128 | 1248077 | 124764 | 1.02ms | 1.325ms | 1.761ms |
| Granian | 8 | 256 | 1386265 | 138603 | 1.833ms | 4.004ms | 5.475ms |
| Uvicorn zttp | 2 | 64 | 358914 | 35892 | 1.78ms | 2.527ms | 2.564ms |
| Uvicorn zttp | 4 | 128 | 653175 | 65302 | 1.952ms | 3.889ms | 4.654ms |
| Uvicorn zttp | 8 | 256 | 966608 | 96640 | 2.634ms | 4.367ms | 5.682ms |


### Long I/O

Plain-text responses after a simulated I/O wait of 10ms.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 256 | 232260 | 23243 | 10.965ms | 11.902ms | 12.419ms |
| punkasgi | 4 | 512 | 471851 | 47214 | 10.765ms | 12.105ms | 13.392ms |
| punkasgi | 8 | 1024 | 912465 | 91259 | 10.702ms | 12.545ms | 31.2ms |
| Granian | 2 | 256 | 214581 | 21477 | 11.859ms | 12.546ms | 13.03ms |
| Granian | 4 | 512 | 427671 | 42799 | 11.894ms | 12.86ms | 13.867ms |
| Granian | 8 | 1024 | 818322 | 81873 | 11.904ms | 13.15ms | 17.488ms |
| Uvicorn zttp | 2 | 256 | 187100 | 18729 | 13.626ms | 15.447ms | 17.114ms |
| Uvicorn zttp | 4 | 512 | 369828 | 37014 | 13.745ms | 16.306ms | 18.769ms |
| Uvicorn zttp | 8 | 1024 | 675065 | 67571 | 14.389ms | 17.181ms | 21.546ms |


### WebSockets

Broadcasting: concurrent clients each send a fixed number of messages and receive the
messages of every connected client. Messages are 1 KB JSON text frames, no compression
(not every server negotiates permessage-deflate). Throughput is in messages per second.
Broadcasting needs every client in the same process, so only punkasgi scales its threads:
Granian (with `--runtime-threads 2`) and Uvicorn run a single worker.

| Clients | Server | Threads / workers | Receive throughput | Combined throughput |
| --- | --- | --- | --- | --- |
| 16 | punkasgi | 2 | 210124 | 223257 |
| 16 | punkasgi | 4 | 256538 | 272572 |
| 16 | punkasgi | 8 | 255590 | 271565 |
| 16 | Granian | 1 | 255531 | 271501 |
| 16 | Uvicorn zttp | 1 | 112209 | 119222 |
| 32 | punkasgi | 2 | 237529 | 244951 |
| 32 | punkasgi | 4 | 265415 | 273709 |
| 32 | punkasgi | 8 | 259790 | 267908 |
| 32 | Granian | 1 | 253618 | 261544 |
| 32 | Uvicorn zttp | 1 | 111509 | 114994 |
| 64 | punkasgi | 2 | 263699 | 267820 |
| 64 | punkasgi | 4 | 263848 | 267971 |
| 64 | punkasgi | 8 | 263304 | 267418 |
| 64 | Granian | 1 | 253258 | 257215 |
| 64 | Uvicorn zttp | 1 | 112398 | 114155 |


### Resources

CPU time and memory (proportional set size) of the whole server process tree during the
10 seconds measurement run of the *echo* benchmark at 8 threads / workers. CPU is the
aggregate utilisation, where 100% is one core; idle memory is sampled after startup, before
any traffic.

| Server | Benchmark | RPS | CPU per request | CPU | Idle memory | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
| punkasgi | HTTP/1.1 echo 10KB (iter) | 100098 | 74.3µs | 721% | 60.9MB | 81.7MB |
| Granian | HTTP/1.1 echo 10KB (iter) | 128925 | 77.6µs | 969% | 53.3MB | 93.7MB |
| Uvicorn zttp | HTTP/1.1 echo 10KB (iter) | 139643 | 49.9µs | 674% | 221.9MB | 235.4MB |
| punkasgi | HTTP/2 echo 10KB (iter) | 127684 | 59.9µs | 741% | 61.1MB | 155.2MB |
| Granian | HTTP/2 echo 10KB (iter) | 120431 | 87.1µs | 1013% | 55.4MB | 151.1MB |
| Uvicorn zttp | HTTP/2 echo 10KB (iter) | 104765 | 66.8µs | 682% | 222.7MB | 286.8MB |

