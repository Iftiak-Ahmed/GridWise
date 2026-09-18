"""Smoke test of the full HTTP layer with NO Groq API key configured.

This exercises exactly the "provider unavailable" path every request will take in this
sandbox: LLMUnavailableError -> fallback_interpreter -> guardrails -> optimizer -> validator
-> response, plus /health, malformed JSON handling, and schema validation. It does not
prove LLM correctness (see run_api_smoke.py for that with a real key) but proves the service
never crashes and always returns a valid, constraint-satisfying plan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import validator
from app.main import app

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "public_cases.json"


def main() -> int:
    client = TestClient(app)

    health = client.get("/health")
    print(f"GET /health -> {health.status_code} {health.json()}")
    assert health.status_code == 200 and health.json() == {"status": "ok"}

    bad = client.post("/optimize-energy", content="{not valid json", headers={"content-type": "application/json"})
    print(f"POST malformed JSON -> {bad.status_code} {bad.json()}")
    assert bad.status_code == 400

    bad2 = client.post("/optimize-energy", json={"scenario_id": "x"})
    print(f"POST missing fields -> {bad2.status_code} {bad2.json()}")
    assert bad2.status_code == 400

    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    passed = 0
    for case in cases:
        req = case["input"]
        resp = client.post("/optimize-energy", json=req)
        if resp.status_code != 200:
            print(f"[FAIL] {case['id']}: HTTP {resp.status_code} {resp.text[:300]}")
            continue
        body = resp.json()
        violations = validator.replay(
            req["hours"], req["battery"], body["directive_interpretation"], body["hourly_plan"]
        )
        note_count_ok = len(body["directive_interpretation"]) == len(req["operator_notes"])
        ok = not violations and note_count_ok and body["scenario_id"] == req["scenario_id"]
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] {case['id']} cost={body['total_cost_bdt']:.2f} BDT plan_summary={body['plan_summary'][:70]!r}")
        for v in violations:
            print(f"    - {v}")

    print(f"\n{passed}/{len(cases)} cases returned a valid, non-crashing response via the fallback path.")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
