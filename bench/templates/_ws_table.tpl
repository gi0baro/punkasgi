| Clients | Server | Threads / workers | Receive throughput | Combined throughput |
| --- | --- | --- | --- | --- |
{{ for concur in [16, 32, 64]: }}
{{ for key in _data.keys(): }}
{{ for run in _data[key].values(): }}
{{ res = run["res"][str(concur)] }}
{{ if res["throughput"]["sum"]: }}
| {{ =concur }} | {{ =key }} | {{ =run["n"] }} | {{ =round(res["throughput"]["recv"]) }} | {{ =round(res["throughput"]["sum"]) }} |
{{ else: }}
| {{ =concur }} | {{ =key }} | {{ =run["n"] }} | N/A | N/A |
{{ pass }}
{{ pass }}
{{ pass }}
{{ pass }}
