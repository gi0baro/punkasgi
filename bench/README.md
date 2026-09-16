# punkasgi benchmarks



Run at: Wed 16 Sep 2026, 18:05    
Environment: AMD Ryzen 7 5700X @ Gentoo Linux 6.18.48 (CPUs: 16)    
CPython 3.14 free-threaded   
punkasgi 0.1.1 (tonio 0.9.17, httpunk 0.4.2)   
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
| punkasgi | 2 | 64 | 497112 | 49707 | 1.285ms | 1.731ms | 2.181ms |
| punkasgi | 4 | 128 | 858569 | 85843 | 1.486ms | 1.918ms | 2.71ms |
| punkasgi | 8 | 256 | 1347031 | 134650 | 1.889ms | 2.294ms | 4.636ms |
| Granian | 2 | 64 | 1746290 | 174594 | 0.365ms | 0.557ms | 0.829ms |
| Granian | 4 | 128 | 2538764 | 253793 | 0.501ms | 1.044ms | 1.46ms |
| Granian | 8 | 256 | 2542769 | 254203 | 1.002ms | 2.344ms | 3.191ms |
| Uvicorn zttp | 2 | 64 | 667917 | 66778 | 0.955ms | 1.539ms | 1.905ms |
| Uvicorn zttp | 4 | 128 | 1155284 | 115506 | 1.103ms | 1.721ms | 2.741ms |
| Uvicorn zttp | 8 | 256 | 1797932 | 179753 | 1.417ms | 2.674ms | 4.487ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 321588 | 32155 | 1.986ms | 2.905ms | 3.507ms |
| punkasgi | 4 | 128 | 585637 | 58559 | 2.178ms | 2.868ms | 3.536ms |
| punkasgi | 8 | 256 | 917508 | 91735 | 2.776ms | 3.285ms | 4.555ms |
| Granian | 2 | 64 | 879896 | 87981 | 0.725ms | 1.08ms | 1.608ms |
| Granian | 4 | 128 | 1294324 | 129397 | 0.985ms | 1.885ms | 2.557ms |
| Granian | 8 | 256 | 1348006 | 134773 | 1.887ms | 3.9ms | 5.108ms |
| Uvicorn zttp | 2 | 64 | 508237 | 50822 | 1.256ms | 2.365ms | 2.833ms |
| Uvicorn zttp | 4 | 128 | 900152 | 90014 | 1.415ms | 2.218ms | 3.121ms |
| Uvicorn zttp | 8 | 256 | 1389211 | 138900 | 1.833ms | 3.563ms | 5.256ms |


### HTTP/2

punkasgi is run with `--http h2`, Granian with `--http 2` and `--runtime-threads 2`,
Uvicorn with `--http zttp --http2`; the client uses HTTP/2 prior knowledge over plain TCP.

#### get 10KB

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 608444 | 60853 | 4.196ms | 4.958ms | 5.45ms |
| punkasgi | 4 | 128 | 1045959 | 104615 | 4.872ms | 5.552ms | 5.896ms |
| punkasgi | 8 | 256 | 1541043 | 154096 | 6.61ms | 7.389ms | 8.493ms |
| Granian | 2 | 64 | 2013098 | 201257 | 1.268ms | 1.988ms | 2.607ms |
| Granian | 4 | 128 | 2469561 | 246883 | 2.056ms | 4.435ms | 5.822ms |
| Granian | 8 | 256 | 2272419 | 227135 | 4.459ms | 10.209ms | 13.294ms |
| Uvicorn zttp | 2 | 64 | 510206 | 51069 | 5.003ms | 9.8ms | 12.423ms |
| Uvicorn zttp | 4 | 128 | 933195 | 93404 | 5.461ms | 10.592ms | 12.459ms |
| Uvicorn zttp | 8 | 256 | 1375732 | 137670 | 7.387ms | 12.799ms | 14.729ms |


#### echo 10KB (iter)

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 470586 | 47072 | 5.427ms | 6.514ms | 7.132ms |
| punkasgi | 4 | 128 | 826587 | 82675 | 6.167ms | 7.055ms | 7.978ms |
| punkasgi | 8 | 256 | 1215413 | 121538 | 8.357ms | 9.564ms | 11.034ms |
| Granian | 2 | 64 | 928398 | 92833 | 2.751ms | 3.639ms | 4.833ms |
| Granian | 4 | 128 | 1247759 | 124779 | 4.082ms | 7.493ms | 9.256ms |
| Granian | 8 | 256 | 1078562 | 107848 | 9.394ms | 18.996ms | 24.943ms |
| Uvicorn zttp | 2 | 64 | 415869 | 41630 | 6.128ms | 11.798ms | 16.705ms |
| Uvicorn zttp | 4 | 128 | 736252 | 73681 | 6.91ms | 14.485ms | 15.72ms |
| Uvicorn zttp | 8 | 256 | 1054947 | 105553 | 9.632ms | 16.636ms | 18.175ms |


### Files

An HTTP GET request returning a ~50KB JPEG image, read in full and returned as a single
byte string.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 64 | 233626 | 23364 | 2.735ms | 3.274ms | 3.682ms |
| punkasgi | 4 | 128 | 278805 | 27885 | 4.574ms | 5.913ms | 6.96ms |
| punkasgi | 8 | 256 | 375755 | 37589 | 6.789ms | 10.566ms | 13.829ms |
| Granian | 2 | 64 | 807928 | 80775 | 0.789ms | 1.3ms | 1.539ms |
| Granian | 4 | 128 | 1199538 | 119921 | 1.061ms | 1.506ms | 2.047ms |
| Granian | 8 | 256 | 1315364 | 131508 | 1.935ms | 4.434ms | 6.033ms |
| Uvicorn zttp | 2 | 64 | 319749 | 31975 | 1.996ms | 3.153ms | 3.533ms |
| Uvicorn zttp | 4 | 128 | 599870 | 59980 | 2.128ms | 3.796ms | 4.52ms |
| Uvicorn zttp | 8 | 256 | 929865 | 92973 | 2.733ms | 4.517ms | 6.306ms |


### Long I/O

Plain-text responses after a simulated I/O wait of 10ms.

| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
| punkasgi | 2 | 256 | 228021 | 22820 | 11.177ms | 12.339ms | 16.229ms |
| punkasgi | 4 | 512 | 467411 | 46765 | 10.906ms | 12.252ms | 14.355ms |
| punkasgi | 8 | 1024 | 902997 | 90341 | 10.782ms | 12.649ms | 34.919ms |
| Granian | 2 | 256 | 214126 | 21428 | 11.907ms | 12.646ms | 13.511ms |
| Granian | 4 | 512 | 422135 | 42247 | 12.062ms | 12.899ms | 13.902ms |
| Granian | 8 | 1024 | 819704 | 82020 | 11.874ms | 13.217ms | 16.721ms |
| Uvicorn zttp | 2 | 256 | 175944 | 17615 | 14.486ms | 16.899ms | 46.582ms |
| Uvicorn zttp | 4 | 512 | 377785 | 37802 | 13.477ms | 15.794ms | 21.013ms |
| Uvicorn zttp | 8 | 1024 | 692296 | 69281 | 14.068ms | 17.436ms | 20.982ms |


### WebSockets

Broadcasting: concurrent clients each send a fixed number of messages and receive the
messages of every connected client. Messages are 1 KB JSON text frames, no compression
(not every server negotiates permessage-deflate). Throughput is in messages per second.
Broadcasting needs every client in the same process, so only punkasgi scales its threads:
Granian (with `--runtime-threads 2`) and Uvicorn run a single worker.

| Clients | Server | Threads / workers | Receive throughput | Combined throughput |
| --- | --- | --- | --- | --- |
| 16 | punkasgi | 2 | 264741 | 281287 |
| 16 | punkasgi | 4 | 264606 | 281144 |
| 16 | punkasgi | 8 | 234119 | 248751 |
| 16 | Granian | 1 | 240708 | 255752 |
| 16 | Uvicorn zttp | 1 | 113420 | 120509 |
| 32 | punkasgi | 2 | 223942 | 230940 |
| 32 | punkasgi | 4 | 258576 | 266656 |
| 32 | punkasgi | 8 | 236995 | 244401 |
| 32 | Granian | 1 | 251175 | 259024 |
| 32 | Uvicorn zttp | 1 | 114104 | 117669 |
| 64 | punkasgi | 2 | 254845 | 258827 |
| 64 | punkasgi | 4 | 259244 | 263294 |
| 64 | punkasgi | 8 | 248672 | 252558 |
| 64 | Granian | 1 | 250603 | 254519 |
| 64 | Uvicorn zttp | 1 | 114803 | 116597 |


### Resources

CPU time and memory (proportional set size) of the whole server process tree during the
10 seconds measurement run of the *echo* benchmark at 8 threads / workers. CPU is the
aggregate utilisation, where 100% is one core; idle memory is sampled after startup, before
any traffic.

| Server | Benchmark | RPS | CPU per request | CPU | Idle memory | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
| punkasgi | HTTP/1.1 echo 10KB (iter) | 91735 | 81.6µs | 733% | 34.5MB | 129.5MB |
| Granian | HTTP/1.1 echo 10KB (iter) | 134773 | 70.3µs | 918% | 53.3MB | 94.0MB |
| Uvicorn zttp | HTTP/1.1 echo 10KB (iter) | 138900 | 50.2µs | 670% | 222.3MB | 236.4MB |
| punkasgi | HTTP/2 echo 10KB (iter) | 121538 | 62.7µs | 740% | 34.5MB | 99.5MB |
| Granian | HTTP/2 echo 10KB (iter) | 107848 | 88.1µs | 926% | 53.6MB | 146.5MB |
| Uvicorn zttp | HTTP/2 echo 10KB (iter) | 105553 | 66.5µs | 677% | 223.0MB | 288.8MB |

