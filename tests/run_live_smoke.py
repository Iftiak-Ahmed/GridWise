"""Smoke test against the LIVE deployed endpoint — approximates how the judge harness checks
the submission (Participant Guide Sec. 05/08): /health, all 10 public samples through
/optimize-energy, malformed-input robustness, and p95/max latency.

Usage:
    python -m tests.run_live_smoke [base_url]

If base_url is omitted, defaults to the deployed Render URL.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://gridwise-optimizer.onrender.com"
SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "public_cases.json"


def post(base_url: str, path: str, body_bytes: bytes):
    req = urllib.request.Request(
        base_url + path, data=body_bytes, method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            elapsed = time.monotonic() - t0
            return resp.status, json.loads(resp.read().decode()), elapsed
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - t0
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = None
        return exc.code, body, elapsed


def get(base_url: str, path: str):
    req = urllib.request.Request(base_url + path, method="GET")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return resp.status, json.loads(resp.read().decode())


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    print(f"Testing live deployment at {base_url}\n")

    status, body = get(base_url, "/health")
    print(f"GET /health -> {status} {body}")
    assert status == 200 and body == {"status": "ok"}, "health check failed"

    print("\n--- Robustness: malformed input ---")
    for label, body_bytes in [
        ("invalid JSON syntax", b"{not valid json"),
        ("missing required fields", json.dumps({"scenario_id": "X"}).encode()),
        ("wrong top-level type", b"[]"),
    ]:
        status, resp_body, elapsed = post(base_url, "/optimize-energy", body_bytes)
        print(f"  {label}: HTTP {status} ({elapsed:.2f}s) {resp_body}")
        assert status == 400, f"expected 400 for {label}, got {status}"

    print("\n--- Public samples (real LLM path) ---")
    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    passed = 0
    latencies = []
    for case in cases:
        req_body = json.dumps(case["input"]).encode()
        status, resp_body, elapsed = post(base_url, "/optimize-energy", req_body)
        latencies.append(elapsed)
        if status != 200:
            print(f"  [FAIL] {case['id']}: HTTP {status} {resp_body}")
            continue

        ref = case["expected_output"]
        note_count_ok = len(resp_body.get("directive_interpretation", [])) == len(case["input"]["operator_notes"])
        cost_ok = abs(resp_body.get("total_cost_bdt", -1) - ref["total_cost_bdt"]) <= max(0.01, ref["total_cost_bdt"] * 0.001)
        ok = note_count_ok and cost_ok
        if ok:
            passed += 1
        status_label = "PASS" if ok else "FAIL"
        print(f"  [{status_label}] {case['id']} ({elapsed:.2f}s) cost={resp_body.get('total_cost_bdt')} (ref {ref['total_cost_bdt']})")

    latencies.sort()
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    print(f"\n{passed}/{len(cases)} public samples passed.")
    print(f"Latency — p95: {p95:.2f}s, max: {max(latencies):.2f}s (judge tiers: <=5s full credit, <=30s per-request limit)")

    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
