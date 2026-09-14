import datetime
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager


CPU = multiprocessing.cpu_count()
# threads (punkasgi) or workers (granian, uvicorn) each server is run with, and the client
# connections per thread
THREADS = [2, 4, 8]
PER_THREAD = 32
CLK_TCK = os.sysconf("SC_CLK_TCK")
# (clients, messages per client): each client receives clients × messages, ~1.3M per run
WS_CONCURRENCIES = [(16, 5000), (32, 1250), (64, 320)]

# every server runs on the same free-threaded interpreter
BIN = os.environ.get("BENCHMARK_BIN", "")
HERE = os.path.dirname(os.path.abspath(__file__))

SERVERS = {
    "punkasgi": (
        BIN,
        "punkasgi --log-level warning --backlog 2048 {wsmode}--http h{http} --threads {procs} {app}_tonio:app",
    ),
    "granian": (
        BIN,
        "granian --interface asgi --log-level warning --backlog 2048 {wsmode}--http {http} --loop asyncio "
        "--workers {procs} --runtime-threads {rthreads} {app}:app",
    ),
    "uvicorn_h11": (
        BIN,
        f"python {HERE}/uvicorn_main.py --interface asgi3 --no-access-log --log-level warning --http h11 --loop asyncio "
        "--ws {uvws} --workers {procs} {app}:app",
    ),
    "uvicorn_zttp": (
        BIN,
        f"python {HERE}/uvicorn_main.py --interface asgi3 --no-access-log --log-level warning --http zttp {{http2}}--loop asyncio "
        "--ws {uvws} --workers {procs} {app}:app",
    ),
}

TITLES = {
    "punkasgi": "punkasgi",
    "granian": "Granian",
    "uvicorn_h11": "Uvicorn h11",
    "uvicorn_zttp": "Uvicorn zttp",
}


@contextmanager
def server(name, procs=1, rthreads=1, http="1", ws=False, app="app.asgi"):
    prefix, template = SERVERS[name]
    cmd = template.format(
        app=app,
        procs=procs,
        rthreads=rthreads,
        http=http,
        wsmode="--ws " if ws else "--no-ws ",
        http2="--http2 " if http == "2" else "",
        uvws="websockets-sansio" if ws else "none",
    )
    if prefix:
        cmd = f"{prefix}/{cmd}"
    proc = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)  # noqa: S602
    time.sleep(2)
    try:
        yield os.getpgid(proc.pid)
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        time.sleep(1)


def oha(duration, concurrency, endpoint, post=None, h2=False):
    cmd_parts = ["oha", "--no-tui", f"-c {concurrency}", f"-z {duration}s", "--output-format json"]
    if h2:
        cmd_parts.append("--http2")
        cmd_parts.append("-p 4")
    tfile = None
    if post:
        tfile = tempfile.NamedTemporaryFile(delete=False)
        tfile.write(b"x" * post)
        tfile.close()
        cmd_parts.append("-m POST")
        cmd_parts.append(f'-D "{tfile.name}"')
    cmd_parts.append(f"http://127.0.0.1:8000/{endpoint}")
    try:
        proc = subprocess.run(" ".join(cmd_parts), shell=True, check=True, capture_output=True)  # noqa: S602
        data = json.loads(proc.stdout.decode("utf8"))
        return {
            "requests": {
                "total": data["statusCodeDistribution"].get("200", 0),
                "rps": round(data["summary"]["requestsPerSec"] or 0),
            },
            "latency": {
                "avg": data["summary"]["average"] * 1000,
                "p99": data["latencyPercentiles"]["p99"] * 1000,
                "p999": data["latencyPercentiles"]["p99.9"] * 1000,
            },
        }
    except Exception as e:
        print(f"WARN: got exception {e} while loading oha data")
        return {"requests": {"total": 0, "rps": 0}, "latency": {"avg": None, "p99": None, "p999": None}}
    finally:
        if tfile:
            os.unlink(tfile.name)


def wsb(concurrency, msgs):
    cmd = f"{BIN}/python {HERE}/ws/benchmark.py"
    env = {**os.environ, "BENCHMARK_CONCURRENCY": str(concurrency), "BENCHMARK_MSGNO": str(msgs)}
    try:
        proc = subprocess.run(cmd, shell=True, check=True, capture_output=True, env=env)  # noqa: S602
        return json.loads(proc.stdout.decode("utf8"))
    except Exception as e:
        print(f"WARN: got exception {e} while loading wsbench data")
        return {
            "timings": {k: {"avg": 0, "max": 0, "min": 0} for k in ("recv", "send", "sum", "all")},
            "throughput": {"recv": 0, "send": 0, "all": 0, "sum": 0},
        }


def group_pids(pgid):
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                fields = f.read().rpartition(")")[2].split()
        except OSError:
            continue
        if int(fields[2]) == pgid:
            pids.append(int(entry))
    return pids


def cpu_seconds(pids):
    total = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rpartition(")")[2].split()
        except OSError:
            continue
        total += int(fields[11]) + int(fields[12])
    return total / CLK_TCK


def pss_kb(pids):
    total = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        total += int(line.split()[1])
                        break
        except OSError:
            continue
    return total


class Resources:
    # CPU time and PSS memory of the whole server process group: workers are children of the
    # supervisor and share its group, so the sums cover single- and multi-process servers alike
    def __init__(self, pgid):
        self.pgid = pgid
        self.idle_kb = pss_kb(group_pids(pgid))
        self.peak_kb = 0
        self.cpu_s = 0
        self.wall_s = 0

    def _sample(self, stop):
        while not stop.is_set():
            self.peak_kb = max(self.peak_kb, pss_kb(group_pids(self.pgid)))
            stop.wait(0.25)

    def measure(self, fn):
        pids = group_pids(self.pgid)
        stop = threading.Event()
        sampler = threading.Thread(target=self._sample, args=(stop,))
        cpu, wall = cpu_seconds(pids), time.monotonic()
        sampler.start()
        try:
            return fn()
        finally:
            self.cpu_s = cpu_seconds(pids) - cpu
            self.wall_s = time.monotonic() - wall
            stop.set()
            sampler.join()

    def report(self, requests):
        return {
            "idle_kb": self.idle_kb,
            "peak_kb": self.peak_kb,
            "cpu_us_req": self.cpu_s * 1_000_000 / requests if requests else None,
            "cpu_pct": self.cpu_s / self.wall_s * 100 if self.wall_s else None,
        }


def benchmark(endpoint, concurrency, pgid, post=None, h2=False):
    resources = Resources(pgid)
    # primer
    oha(4, 8, endpoint, post=post, h2=h2)
    time.sleep(1)
    # warm up
    oha(3, concurrency, endpoint, post=post, h2=h2)
    time.sleep(2)
    result = resources.measure(lambda: oha(10, concurrency, endpoint, post=post, h2=h2))
    result["resources"] = resources.report(result["requests"]["total"])
    time.sleep(3)
    return result


def benchmark_ws():
    results = {}
    for concurrency, msgs in WS_CONCURRENCIES:
        results[concurrency] = wsb(concurrency, msgs)
        time.sleep(2)
    return results


BENCHES = {"get 10KB": ("b10k", {}), "echo 10KB (iter)": ("echoi", {"post": 10 * 1024})}
IO_BENCHES = {"10ms": ("io10", {})}
FILES_BENCHES = {"files": ("fb", {})}


def _http(servers, benches, per_thread=PER_THREAD, http="1", h2=False):
    # every server at every thread count; the client concurrency grows with the threads
    results = {}
    for name, sopts in servers:
        results[TITLES[name]] = {}
        for key, (route, opts) in benches.items():
            for procs in THREADS:
                concurrency = per_thread * procs
                with server(name, procs=procs, http=http, **sopts) as pgid:
                    results[TITLES[name]][f"{key} N{procs}"] = {
                        "bench": key,
                        "n": procs,
                        "c": concurrency,
                        "res": benchmark(route, concurrency, pgid, h2=h2, **opts),
                    }
    return results


def http1():
    return _http([("punkasgi", {}), ("granian", {}), ("uvicorn_zttp", {})], BENCHES)


def http2():
    return _http([("punkasgi", {}), ("granian", {"rthreads": 2}), ("uvicorn_zttp", {})], BENCHES, http="2", h2=True)


def io():
    return _http([("punkasgi", {}), ("granian", {}), ("uvicorn_zttp", {})], IO_BENCHES, per_thread=PER_THREAD * 4)


def files():
    return _http([("punkasgi", {}), ("granian", {}), ("uvicorn_zttp", {})], FILES_BENCHES)


def ws():
    # broadcasting needs every client in the same process: punkasgi scales its threads,
    # the process-based servers run a single worker
    results = {}
    for name, threads, sopts in [
        ("punkasgi", THREADS, {}),
        ("granian", [1], {"rthreads": 2}),
        ("uvicorn_zttp", [1], {}),
    ]:
        results[TITLES[name]] = {}
        for procs in threads:
            with server(name, procs=procs, ws=True, app="ws.app.asgi", **sopts):
                results[TITLES[name]][f"N{procs}"] = {"n": procs, "res": benchmark_ws()}
    return results


def version(prefix, package):
    cmd = [f"{prefix}/python", "-c", f"import importlib.metadata as m; print(m.version('{package}'))"]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603


def run():
    all_benchmarks = {"http1": http1, "http2": http2, "io": io, "files": files, "ws": ws}
    selected = sys.argv[1:] or list(all_benchmarks)
    run_benchmarks = [key for key in all_benchmarks if key in selected]

    now = datetime.datetime.now(datetime.UTC)
    results = {}
    for key in run_benchmarks:
        results[key] = all_benchmarks[key]()

    with open("results/data.json", "w") as f:
        f.write(
            json.dumps(
                {
                    "cpu": CPU,
                    "run_at": int(now.timestamp()),
                    "results": results,
                    "versions": {
                        "punkasgi": version(BIN, "punkasgi"),
                        "tonio": version(BIN, "tonio"),
                        "httpunk": version(BIN, "httpunk"),
                        "granian": version(BIN, "granian"),
                        "uvicorn": version(BIN, "uvicorn"),
                    },
                }
            )
        )


if __name__ == "__main__":
    run()
