# punkasgi benchmarks



Run at: Mon 14 Sep 2026, 17:22    
Environment: AMD Ryzen 7 5700X @ Gentoo Linux 6.18.48 (CPUs: 16)    
CPython 3.14 free-threaded   
punkasgi 0.1.0 (tonio 0.9.17, httpunk 0.4.1)   
Granian 2.8.2   
Uvicorn 0.53.0   

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
| punkasgi | 2 | 64 | 541064 | 54101 | 1.18ms | 1.437ms | 1.697ms |
| punkasgi | 4 | 128 | 906758 | 90656 | 1.406ms | 1.685ms | 2.031ms |
| punkasgi | 8 | 256 | 1357692 | 135734 | 1.874ms | 2.35ms | 4.467ms |
| Granian | 2 | 64 | 1796188 | 179567 | 0.354ms | 0.528ms | 0.733ms |
| Granian | 4 | 128 | 2584959 | 258387 | 0.492ms | 1.012ms | 1.478ms |
| Granian | 8 | 256 | 2559558 | 255897 | 0.993ms | 2.323ms | 3.168ms |
| Uvicorn zttp | 2 | 64 | 713764 | 71363 | 0.894ms | 1.189ms | 1.416ms |
| Uvicorn zttp | 4 | 128 | 1237473 | 123719 | 1.03ms | 1.768ms | 2.294ms |
| Uvicorn zttp | 8 | 256 | 1787024 | 178673 | 1.425ms | 2.099ms | 3.519ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 354066 | 35408 | 1.803ms | 2.447ms | 2.918ms |
| punkasgi | 4 | 128 | 614890 | 61489 | 2.074ms | 2.72ms | 3.286ms |
| punkasgi | 8 | 256 | 930593 | 93056 | 2.739ms | 3.427ms | 5.178ms |
| Granian | 2 | 64 | 927720 | 92762 | 0.687ms | 1.002ms | 1.678ms |
| Granian | 4 | 128 | 1303744 | 130338 | 0.976ms | 1.902ms | 2.734ms |
| Granian | 8 | 256 | 1362101 | 136175 | 1.87ms | 3.929ms | 5.185ms |
| Uvicorn zttp | 2 | 64 | 567156 | 56713 | 1.125ms | 1.535ms | 1.895ms |
| Uvicorn zttp | 4 | 128 | 955155 | 95504 | 1.334ms | 2.162ms | 2.821ms |
| Uvicorn zttp | 8 | 256 | 1397974 | 139780 | 1.821ms | 2.633ms | 4.037ms |


### HTTP/2

punkasgi is run with `--http h2`, Granian with `--http 2` and `--runtime-threads 2`,
Uvicorn with `--http zttp --http2`; the client uses HTTP/2 prior knowledge over plain TCP.

#### get 10KB

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 612577 | 61270 | 4.164ms | 4.831ms | 6.19ms |
| punkasgi | 4 | 128 | 1015347 | 101556 | 5.013ms | 6.086ms | 8.687ms |
| punkasgi | 8 | 256 | 1446274 | 144631 | 7.019ms | 9.815ms | 12.187ms |
| Granian | 2 | 64 | 2067453 | 206670 | 1.234ms | 1.839ms | 2.215ms |
| Granian | 4 | 128 | 2715461 | 271463 | 1.873ms | 3.92ms | 5.102ms |
| Granian | 8 | 256 | 2529849 | 252866 | 4.018ms | 8.861ms | 11.305ms |
| Uvicorn zttp | 2 | 64 | 549100 | 54956 | 4.644ms | 7.494ms | 10.125ms |
| Uvicorn zttp | 4 | 128 | 989886 | 99079 | 5.139ms | 10.504ms | 11.527ms |
| Uvicorn zttp | 8 | 256 | 1355942 | 135668 | 7.488ms | 14.024ms | 14.982ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 492658 | 49282 | 5.18ms | 6.006ms | 6.934ms |
| punkasgi | 4 | 128 | 818855 | 81911 | 6.224ms | 7.756ms | 10.495ms |
| punkasgi | 8 | 256 | 1131054 | 113140 | 8.976ms | 12.811ms | 14.114ms |
| Granian | 2 | 64 | 973099 | 97300 | 2.622ms | 3.681ms | 3.973ms |
| Granian | 4 | 128 | 1315079 | 131476 | 3.869ms | 6.864ms | 8.363ms |
| Granian | 8 | 256 | 1195499 | 119552 | 8.482ms | 16.009ms | 19.328ms |
| Uvicorn zttp | 2 | 64 | 452717 | 45318 | 5.633ms | 9.266ms | 10.962ms |
| Uvicorn zttp | 4 | 128 | 787308 | 78808 | 6.459ms | 13.686ms | 15.181ms |
| Uvicorn zttp | 8 | 256 | 1060748 | 106151 | 9.558ms | 14.634ms | 15.94ms |


### Files

An HTTP GET request returning a ~50KB JPEG image, read in full and returned as a single
byte string.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 231169 | 23116 | 2.762ms | 3.328ms | 4.132ms |
| punkasgi | 4 | 128 | 285800 | 28585 | 4.464ms | 5.599ms | 5.826ms |
| punkasgi | 8 | 256 | 373150 | 37327 | 6.833ms | 10.465ms | 11.7ms |
| Granian | 2 | 64 | 887043 | 88696 | 0.718ms | 1.036ms | 1.167ms |
| Granian | 4 | 128 | 1203013 | 120270 | 1.058ms | 1.423ms | 1.859ms |
| Granian | 8 | 256 | 1338724 | 133847 | 1.901ms | 4.299ms | 5.919ms |
| Uvicorn zttp | 2 | 64 | 343564 | 34357 | 1.858ms | 2.569ms | 3.338ms |
| Uvicorn zttp | 4 | 128 | 624977 | 62498 | 2.04ms | 3.983ms | 4.695ms |
| Uvicorn zttp | 8 | 256 | 930530 | 93033 | 2.733ms | 4.36ms | 6.388ms |


### Long I/O

Plain-text responses after a simulated I/O wait of 10ms.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 256 | 230288 | 23048 | 11.049ms | 12.2ms | 17.304ms |
| punkasgi | 4 | 512 | 468802 | 46904 | 10.842ms | 12.083ms | 20.331ms |
| punkasgi | 8 | 1024 | 943490 | 94396 | 10.761ms | 12.397ms | 32.205ms |
| Granian | 2 | 256 | 215413 | 21561 | 11.826ms | 12.545ms | 12.966ms |
| Granian | 4 | 512 | 433423 | 43372 | 11.706ms | 12.848ms | 24.525ms |
| Granian | 8 | 1024 | 862985 | 86349 | 11.739ms | 13.174ms | 49.676ms |
| Uvicorn zttp | 2 | 256 | 198204 | 19836 | 12.857ms | 14.777ms | 16.107ms |
| Uvicorn zttp | 4 | 512 | 397136 | 39735 | 12.801ms | 15.659ms | 19.53ms |
| Uvicorn zttp | 8 | 1024 | 738123 | 73856 | 13.73ms | 16.926ms | 51.71ms |


### WebSockets

Broadcasting: concurrent clients each send a fixed number of messages and receive the
messages of every connected client. Messages are 1 KB JSON text frames, no compression
(not every server negotiates permessage-deflate). Throughput is in messages per second.
Broadcasting needs every client in the same process, so only punkasgi scales its threads:
Granian (with `--runtime-threads 2`) and Uvicorn run a single worker.

| Clients | Server | Threads / workers | Receive throughput | Combined throughput |
| --- | --- | --- | --- | --- |
| 16 | punkasgi | 2 | 202039 | 214666 |
| 16 | punkasgi | 4 | 258180 | 274316 |
| 16 | punkasgi | 8 | 249910 | 265530 |
| 16 | Granian | 1 | 262135 | 278518 |
| 16 | Uvicorn zttp | 1 | 111491 | 118459 |
| 32 | punkasgi | 2 | 229546 | 236719 |
| 32 | punkasgi | 4 | 266341 | 274664 |
| 32 | punkasgi | 8 | 245253 | 252918 |
| 32 | Granian | 1 | 252144 | 260023 |
| 32 | Uvicorn zttp | 1 | 115579 | 119191 |
| 64 | punkasgi | 2 | 264691 | 268827 |
| 64 | punkasgi | 4 | 259917 | 263978 |
| 64 | punkasgi | 8 | 264383 | 268514 |
| 64 | Granian | 1 | 257854 | 261883 |
| 64 | Uvicorn zttp | 1 | 116468 | 118288 |


### Resources

CPU time and memory (proportional set size) of the whole server process tree during the
10 seconds measurement run of the *echo* benchmark at 8 threads / workers. CPU is the
aggregate utilisation, where 100% is one core; idle memory is sampled after startup, before
any traffic.

| Server | Benchmark | RPS | CPU per request | CPU | Idle memory | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
| punkasgi | HTTP/1.1 echo 10KB (iter) | 93056 | 80.7µs | 736% | 33.9MB | 130.2MB |
| Granian | HTTP/1.1 echo 10KB (iter) | 136175 | 71.5µs | 944% | 53.3MB | 93.4MB |
| Uvicorn zttp | HTTP/1.1 echo 10KB (iter) | 139780 | 50.0µs | 678% | 223.3MB | 272.5MB |
| punkasgi | HTTP/2 echo 10KB (iter) | 113140 | 69.8µs | 763% | 34.0MB | 359.0MB |
| Granian | HTTP/2 echo 10KB (iter) | 119552 | 86.7µs | 997% | 53.5MB | 153.7MB |
| Uvicorn zttp | HTTP/2 echo 10KB (iter) | 106151 | 66.1µs | 679% | 222.8MB | 292.1MB |

