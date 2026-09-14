| Server | Benchmark | RPS | CPU per request | CPU | Idle memory | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
{{ for section, label in _sections: }}
{{ for key in data.results[section].keys(): }}
{{ for run in [r for r in data.results[section][key].values() if r["n"] == _n and r["bench"] == _bench]: }}
{{ res = run["res"] }}
{{ rs = res["resources"] }}
| {{ =key }} | {{ =(label + " " + run["bench"]).strip() }} | {{ =res["requests"]["rps"] }} | {{ =fmt_us(rs["cpu_us_req"]) }} | {{ =fmt_pct(rs["cpu_pct"]) }} | {{ =fmt_mb(rs["idle_kb"]) }} | {{ =fmt_mb(rs["peak_kb"]) }} |
{{ pass }}
{{ pass }}
{{ pass }}
