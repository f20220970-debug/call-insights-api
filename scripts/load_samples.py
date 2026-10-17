"""Post the sample calls to a running API and print the results once analysed.

    python scripts/load_samples.py            # API at http://localhost:8000
"""
import json
import sys
import time
from pathlib import Path

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
rows = json.loads((Path(__file__).resolve().parents[1] / "data" / "sample_calls.json").read_text())
with httpx.Client(base_url=API, timeout=30) as c:
    for r in rows:
        r.pop("label")
        resp = c.post("/v1/calls", json=r)
        print(r["call_id"], resp.status_code)
    time.sleep(3)
    for r in rows[:3]:
        print(json.dumps(c.get(f"/v1/calls/{r['call_id']}").json(), indent=1))
    print(json.dumps(c.get("/v1/stats").json(), indent=1))
