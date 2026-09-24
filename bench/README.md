# punkasgi benchmarks



Run at: Thu 24 Sep 2026, 13:18    
Environment: AMD Ryzen 7 5700X @ Gentoo Linux 6.18.48 (CPUs: 16)    
CPython 3.14 free-threaded   
punkasgi 0.1.2 (tonio 0.10.1, httpunk 0.4.4)   
Granian 2.8.3   
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
| punkasgi | 2 | 64 | 583285 | 58322 | 1.094ms | 1.208ms | 1.294ms |
| punkasgi | 4 | 128 | 945293 | 94525 | 1.348ms | 1.595ms | 1.751ms |
| punkasgi | 8 | 256 | 1417142 | 141673 | 1.798ms | 2.163ms | 3.343ms |
| Granian | 2 | 64 | 1829334 | 182895 | 0.348ms | 0.542ms | 0.721ms |
| Granian | 4 | 128 | 2614965 | 261416 | 0.487ms | 0.99ms | 1.457ms |
| Granian | 8 | 256 | 2602680 | 260171 | 0.976ms | 2.278ms | 3.077ms |
| Uvicorn zttp | 2 | 64 | 738488 | 73835 | 0.864ms | 0.985ms | 1.059ms |
| Uvicorn zttp | 4 | 128 | 1265242 | 126495 | 1.008ms | 1.506ms | 1.817ms |
| Uvicorn zttp | 8 | 256 | 1770345 | 176975 | 1.436ms | 2.128ms | 3.269ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 369899 | 36990 | 1.725ms | 1.955ms | 2.38ms |
| punkasgi | 4 | 128 | 621831 | 62178 | 2.05ms | 2.624ms | 3.009ms |
| punkasgi | 8 | 256 | 959954 | 95990 | 2.652ms | 3.22ms | 4.614ms |
| Granian | 2 | 64 | 923429 | 92326 | 0.69ms | 1.124ms | 1.415ms |
| Granian | 4 | 128 | 1326951 | 132672 | 0.96ms | 1.864ms | 2.604ms |
| Granian | 8 | 256 | 1298394 | 129819 | 1.963ms | 4.165ms | 5.323ms |
| Uvicorn zttp | 2 | 64 | 558259 | 55823 | 1.143ms | 1.585ms | 1.854ms |
| Uvicorn zttp | 4 | 128 | 955852 | 95564 | 1.333ms | 2.635ms | 3.215ms |
| Uvicorn zttp | 8 | 256 | 1390513 | 139023 | 1.83ms | 2.674ms | 4.113ms |


### HTTP/2

punkasgi is run with `--http h2`, Granian with `--http 2` and `--runtime-threads 2`,
Uvicorn with `--http zttp --http2`; the client uses HTTP/2 prior knowledge over plain TCP.

#### get 10KB

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 716148 | 71620 | 3.567ms | 3.854ms | 4.467ms |
| punkasgi | 4 | 128 | 1134491 | 113455 | 4.489ms | 5.236ms | 5.574ms |
| punkasgi | 8 | 256 | 1624429 | 162441 | 6.223ms | 7.118ms | 8.594ms |
| Granian | 2 | 64 | 2050648 | 204999 | 1.243ms | 1.666ms | 2.166ms |
| Granian | 4 | 128 | 2714477 | 271366 | 1.873ms | 3.998ms | 5.203ms |
| Granian | 8 | 256 | 2576317 | 257531 | 3.942ms | 8.682ms | 10.947ms |
| Uvicorn zttp | 2 | 64 | 541400 | 54195 | 4.71ms | 9.176ms | 9.346ms |
| Uvicorn zttp | 4 | 128 | 1009394 | 101021 | 5.043ms | 8.425ms | 9.268ms |
| Uvicorn zttp | 8 | 256 | 1364713 | 136559 | 7.429ms | 14.372ms | 15.324ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 561928 | 56191 | 4.541ms | 5.155ms | 5.625ms |
| punkasgi | 4 | 128 | 935102 | 93540 | 5.451ms | 6.294ms | 6.854ms |
| punkasgi | 8 | 256 | 1257147 | 125713 | 8.075ms | 9.441ms | 12.059ms |
| Granian | 2 | 64 | 974374 | 97432 | 2.619ms | 3.298ms | 4.078ms |
| Granian | 4 | 128 | 1321312 | 132128 | 3.854ms | 6.805ms | 8.45ms |
| Granian | 8 | 256 | 1211623 | 121107 | 8.375ms | 15.883ms | 19.431ms |
| Uvicorn zttp | 2 | 64 | 453167 | 45361 | 5.63ms | 8.297ms | 11.962ms |
| Uvicorn zttp | 4 | 128 | 786348 | 78710 | 6.475ms | 12.388ms | 14.026ms |
| Uvicorn zttp | 8 | 256 | 1059549 | 106010 | 9.576ms | 17.02ms | 17.949ms |


### Files

An HTTP GET request returning a ~50KB JPEG image, read in full and returned as a single
byte string.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 263019 | 26304 | 2.426ms | 2.981ms | 3.328ms |
| punkasgi | 4 | 128 | 401791 | 40181 | 3.176ms | 3.702ms | 3.894ms |
| punkasgi | 8 | 256 | 486343 | 48643 | 5.232ms | 7.784ms | 8.267ms |
| Granian | 2 | 64 | 912540 | 91235 | 0.698ms | 1.077ms | 1.355ms |
| Granian | 4 | 128 | 1247129 | 124694 | 1.021ms | 1.425ms | 1.844ms |
| Granian | 8 | 256 | 1377428 | 137716 | 1.846ms | 4.046ms | 5.583ms |
| Uvicorn zttp | 2 | 64 | 354626 | 35462 | 1.8ms | 2.053ms | 2.755ms |
| Uvicorn zttp | 4 | 128 | 651756 | 65170 | 1.956ms | 3.752ms | 4.44ms |
| Uvicorn zttp | 8 | 256 | 961656 | 96149 | 2.649ms | 4.191ms | 5.794ms |


### Long I/O

Plain-text responses after a simulated I/O wait of 10ms.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 256 | 231367 | 23157 | 11.02ms | 12.149ms | 12.634ms |
| punkasgi | 4 | 512 | 464781 | 46510 | 10.926ms | 12.104ms | 18.174ms |
| punkasgi | 8 | 1024 | 905730 | 90605 | 10.74ms | 12.373ms | 25.949ms |
| Granian | 2 | 256 | 214464 | 21465 | 11.871ms | 12.508ms | 13.028ms |
| Granian | 4 | 512 | 424464 | 42471 | 11.969ms | 12.855ms | 13.944ms |
| Granian | 8 | 1024 | 817611 | 81803 | 11.933ms | 13.192ms | 19.508ms |
| Uvicorn zttp | 2 | 256 | 205642 | 20582 | 12.374ms | 14.839ms | 16.198ms |
| Uvicorn zttp | 4 | 512 | 378850 | 37913 | 13.419ms | 15.674ms | 17.325ms |
| Uvicorn zttp | 8 | 1024 | 667768 | 66836 | 14.543ms | 17.493ms | 22.816ms |


### WebSockets

Broadcasting: concurrent clients each send a fixed number of messages and receive the
messages of every connected client. Messages are 1 KB JSON text frames, no compression
(not every server negotiates permessage-deflate). Throughput is in messages per second.
Broadcasting needs every client in the same process, so only punkasgi scales its threads:
Granian (with `--runtime-threads 2`) and Uvicorn run a single worker.

| Clients | Server | Threads / workers | Receive throughput | Combined throughput |
| --- | --- | --- | --- | --- |
| 16 | punkasgi | 2 | 205662 | 218516 |
| 16 | punkasgi | 4 | 255039 | 270979 |
| 16 | punkasgi | 8 | 253487 | 269330 |
| 16 | Granian | 1 | 253152 | 268974 |
| 16 | Uvicorn zttp | 1 | 115074 | 122266 |
| 32 | punkasgi | 2 | 232368 | 239629 |
| 32 | punkasgi | 4 | 262436 | 270637 |
| 32 | punkasgi | 8 | 252386 | 260273 |
| 32 | Granian | 1 | 253962 | 261899 |
| 32 | Uvicorn zttp | 1 | 113367 | 116910 |
| 64 | punkasgi | 2 | 257203 | 261221 |
| 64 | punkasgi | 4 | 261462 | 265547 |
| 64 | punkasgi | 8 | 265762 | 269914 |
| 64 | Granian | 1 | 250492 | 254406 |
| 64 | Uvicorn zttp | 1 | 116406 | 118225 |


### Resources

CPU time and memory (proportional set size) of the whole server process tree during the
10 seconds measurement run of the *echo* benchmark at 8 threads / workers. CPU is the
aggregate utilisation, where 100% is one core; idle memory is sampled after startup, before
any traffic.

| Server | Benchmark | RPS | CPU per request | CPU | Idle memory | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
| punkasgi | HTTP/1.1 echo 10KB (iter) | 95990 | 77.9µs | 728% | 60.8MB | 163.8MB |
| Granian | HTTP/1.1 echo 10KB (iter) | 129819 | 77.1µs | 971% | 53.3MB | 92.8MB |
| Uvicorn zttp | HTTP/1.1 echo 10KB (iter) | 139023 | 50.2µs | 675% | 222.5MB | 237.4MB |
| punkasgi | HTTP/2 echo 10KB (iter) | 125713 | 60.6µs | 739% | 60.9MB | 154.9MB |
| Granian | HTTP/2 echo 10KB (iter) | 121107 | 85.9µs | 1002% | 53.5MB | 149.4MB |
| Uvicorn zttp | HTTP/2 echo 10KB (iter) | 106010 | 66.1µs | 679% | 223.2MB | 287.2MB |

