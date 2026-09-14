| Server | Threads / workers | Concurrency | Total requests | RPS | avg latency | p99 latency | p99.9 latency |
| --- | --- | --- | --- | --- | --- | --- | --- |
{{ for key in _data.keys(): }}
{{ for run in [r for r in _data[key].values() if r["bench"] == _bench]: }}
{{ res = run["res"] }}
| {{ =key }} | {{ =run["n"] }} | {{ =run["c"] }} | {{ =res["requests"]["total"] }} | {{ =res["requests"]["rps"] }} | {{ =fmt_ms(res["latency"]["avg"]) }} | {{ =fmt_ms(res["latency"]["p99"]) }} | {{ =fmt_ms(res["latency"]["p999"]) }} |
{{ pass }}
{{ pass }}
