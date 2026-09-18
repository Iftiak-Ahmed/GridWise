"""End-to-end smoke test through the real FastAPI app, including the live LLM call.

Requires GROQ_API_KEY to be set (loaded from .env). Runs the public samples through
the actual /optimize-energy handler (in-process, no server needed) and replays each
returned plan with the independent validator to confirm downstream application, not just
schema shape.

Usage:
    python -m tests.run_api_smoke
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import validator
from app.config import GROQ_API_KEY
from app.main import app

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "public_cases.json"


def main() -> int:
    if not GROQ_API_KEY:
        print("GROQ_API_KEY is not set — skipping live LLM smoke test.")
        print("Set it in .env to exercise the real interpretation path.")
        return 0

    client = TestClient(app)

    health = client.get("/health")
    print(f"GET /health -> {health.status_code} {health.json()}")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    passed = 0
    for case in cases:
        req = case["input"]
        start = time.monotonic()
        resp = client.post("/optimize-energy", json=req)
        elapsed = time.monotonic() - start

        if resp.status_code != 200:
            print(f"[FAIL] {case['id']}: HTTP {resp.status_code} {resp.text[:300]}")
            continue

        body = resp.json()
        directive_interpretation = body["directive_interpretation"]
        plan = body["hourly_plan"]

        # Rebuild directives in the internal shape the validator expects.
        violations = validator.replay(req["hours"], req["battery"], directive_interpretation, plan)

        note_count_ok = len(directive_interpretation) == len(req["operator_notes"])
        status = "PASS" if not violations and note_count_ok else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"[{status}] {case['id']} ({elapsed:.2f}s) cost={body['total_cost_bdt']:.2f} BDT")
        for v in violations:
            print(f"    - {v}")
        if not note_count_ok:
            print(f"    - expected {len(req['operator_notes'])} interpretation entries, got {len(directive_interpretation)}")

    print(f"\n{passed}/{len(cases)} cases passed end-to-end.")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
