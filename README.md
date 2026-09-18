# GridWise Optimizer — BUP CSE Fest 2026 Preliminary

An LLM-assisted 24-hour campus energy scheduling service built for the GridWise preliminary
challenge. It exposes `GET /health` and `POST /optimize-energy`, interprets natural-language
operator notes with a language model, deterministically guardrails that interpretation, and
solves an exact linear program to produce a minimum-cost, constraint-valid 24-hour schedule.

## Architecture

```
Energy Data + Operator Notes
        |
        v
  LLM Interpreter        <- Groq (GPT-OSS 120B by default)
        |                    the ONLY component allowed to decide what a note means
        v
  Guardrail Validator     <- deterministic Python; forces malformed/unsupported output
        |                    to a safe no_op instead of crashing or inventing a rule
        v
  Math Optimizer          <- exact LP (PuLP + CBC); minimizes grid cost subject to
        |                    energy balance, battery, and directive constraints
        v
  Final Validator          <- independently replays the plan hour-by-hour to confirm
        |                    every constraint and directive actually holds
        v
  API Response (JSON)
```

- **`app/llm_interpreter.py`** — the mandatory LLM step (Participant Guide Sec. 04). Sends all
  of a scenario's operator notes to the LLM in one call and asks for strict JSON back. This is
  the only place that performs natural-language understanding; nothing downstream re-interprets
  the notes.
- **`app/guardrails.py`** — treats the LLM's JSON as untrusted. Every entry is checked against
  the exact required shape (directive type, hours, numeric ranges) from the Problem Statement;
  anything that fails is demoted to `no_op` rather than passed through.
- **`app/optimizer.py`** — a linear program (not a heuristic) that minimizes
  `sum(grid_kwh[h] * tariff_bdt_per_kwh[h])` subject to energy balance, battery bounds/rate
  limits, effective solar, and every validated directive, solved exactly with the CBC solver.
- **`app/validator.py`** — replays the returned plan the same way the judge is described as
  doing, so any internal inconsistency is caught before responding (and is reused by the test
  suite to check the optimizer against the public sample pack).
- **`app/fallback_interpreter.py`** — a small regex/keyword safety net used **only** when the
  LLM call itself fails (timeout, missing key, provider outage, non-JSON response). It is never
  the primary interpreter and every entry it produces is tagged
  `[fallback-heuristic: LLM unavailable]` in the response's `explanation` field so it's
  auditable. See **Known Limitations** below.

## Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | API key for the LLM used to interpret `operator_notes`. Free, no card required — get one at [console.groq.com/keys](https://console.groq.com/keys). |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Model id for interpretation. |
| `LLM_TIMEOUT_SECONDS` | No | `12` | Per-call timeout budget for the LLM request. |
| `PORT` | No | `8000` | Port the HTTP server binds to. |

Copy `.env.example` to `.env` and fill in `GROQ_API_KEY`. **Never commit `.env`.**

## LLM role & guardrails (summary)

The LLM (GPT-OSS 120B via Groq) is given the directive-type spec and every operator note in one
call, and returns one structured interpretation per note as JSON. Its output is never trusted
directly:

- `directive_type` must be one of the six supported types, else the entry becomes `no_op`.
- `hours` must be unique ascending integers 0-23.
- `solar_reduction.factor` must be in `[0, 1]` (usable fraction remaining, e.g. an 80%
  reduction → `factor = 0.2`).
- `minimum_battery_reserve.minimum_energy_kwh` and `max_grid_window.max_grid_kwh` must be
  finite and non-negative (reserve additionally capped at battery capacity).
- Exactly one entry per note, covering `note_index` 0..N-1; missing/duplicate entries are
  filled/deduped with `no_op`.
- `no_op` ⇔ `applies=false` and `structured_adjustment=null`; every other directive requires
  `applies=true`.

Only interpretations that pass all of the above ever reach the optimizer.

## Optimizer & solver

- **Library:** [PuLP](https://coin-or.github.io/pulp/) with the bundled CBC solver (open
  source, no external service, solves in well under a second for this problem size).
- **Formulation:** one LP per request — `grid`, `solar_used`, `charge`, `discharge`, and
  `battery_energy` variables for each of the 24 hours, with hard constraints for energy
  balance, battery bounds/rate limits, effective solar (after `solar_reduction`), reserve
  floors (`minimum_battery_reserve`), forced-zero charge/discharge windows, grid caps
  (`max_grid_window`), and end-of-day neutrality. A negligible cycling-regularization term
  (1e-6 per kWh) discourages pointless simultaneous charge+discharge in degenerate optima
  without measurably affecting cost.
- **Infeasibility fallback:** organizer-valid scoring scenarios are guaranteed feasible, but
  malformed/adversarial hidden input could combine into infeasible constraints. If the fully
  constrained LP is infeasible, directive groups are progressively relaxed
  (`max_grid_window` → `minimum_battery_reserve` → `no_discharge_window` → `no_charge_window`
  → `solar_reduction`) until a valid schedule exists, and `plan_summary` says so — this trades
  a small amount of correctness credit on a malformed case for never returning a 500 or crash.

## Local quickstart

Requires Python 3.11+. (CBC ships with the `pulp` wheel on Windows/macOS/Linux — no separate
solver install needed for local runs; the Docker image installs the `coinor-cbc` system
package explicitly for portability.)

```powershell
# 1. Clone and enter the repo
git clone <your-repo-url>
cd GridWise-Optimizer

# 2. Create a virtual environment and install dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Configure environment variables
copy .env.example .env
# then edit .env and set GROQ_API_KEY

# 4. Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

(bash/macOS/Linux equivalent: `python3 -m venv .venv && source .venv/bin/activate`, `cp` instead
of `copy`.)

### Test /health

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Test /optimize-energy against a public sample

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  --data-binary @- <<'EOF'
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [ ... 24 hourly entries, see samples/public_cases.json ... ],
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
EOF
```

Full worked request/response bodies for all 10 public cases are in
[`samples/public_cases.json`](samples/public_cases.json).

### Automated test suite

Three scripts, from fastest/most-offline to full end-to-end:

```bash
# 1. Deterministic core only (guardrails + LP optimizer + replay validator).
#    No API key or network needed. Feeds each public sample's published ground-truth
#    directive_interpretation through the real guardrail/optimizer/validator code and
#    checks every plan is constraint-valid with quality_ratio == 1.0 against the reference.
python -m tests.run_offline_checks

# 2. Full HTTP layer (FastAPI in-process) with NO API key — exercises /health, malformed-JSON
#    handling, schema validation, and the fallback-interpreter safety net end-to-end.
python -m tests.run_no_key_smoke

# 3. Full HTTP layer WITH a real GROQ_API_KEY set in .env — exercises the actual LLM
#    interpretation path against all 10 public samples and prints per-case latency.
python -m tests.run_api_smoke
```

Expected result for (1) and (2): `10/10 cases passed`. Test (3) requires network access and a
valid key; expect it to also fully pass, with per-case latency typically well under the 30s
judge timeout.

## Docker fallback image

```bash
# Build
docker build -t gridwise-optimizer:latest .

# Run (no secrets baked into the image — pass the key at runtime)
docker run --rm -p 8000:8000 \
  -e GROQ_API_KEY=your_key_here \
  -e GROQ_MODEL=openai/gpt-oss-120b \
  gridwise-optimizer:latest

# Verify
curl http://localhost:8000/health
```

The image binds to `0.0.0.0:${PORT}` (default `8000`), matches the documented port, and
contains no baked-in credentials — `GROQ_API_KEY` must be supplied via `-e` or your
platform's secret-injection mechanism at runtime.

Published image:

```
docker pull turzaiftiak/gridwise-optimizer:latest
# digest: sha256:4a5d4b9249b0172f5eaad804274b98842e9c91d243f8ee4242a49cced86e6b25
```

Verified locally: built with `docker build`, run with `docker run -p 8000:8000`, and
`GET /health` returned `{"status":"ok"}` before pushing.

## Dependencies

- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — HTTP service.
- [Pydantic v2](https://docs.pydantic.dev/) — request/response schema validation.
- [Groq API](https://console.groq.com/docs) (OpenAI-compatible, called via `httpx`) — LLM calls.
- [PuLP](https://coin-or.github.io/pulp/) + CBC — the deterministic LP optimizer/solver.
- [python-dotenv](https://github.com/theskumar/python-dotenv) — loads `.env` locally.

## Known limitations

- **Fallback interpreter is a safety net, not a substitute for the LLM.** It only activates
  when the Groq API call itself fails (bad/missing key, network/timeout error, non-JSON
  response). It uses simple regex/keyword matching and will not generalize to arbitrary
  paraphrasing the way the LLM does — its purpose is solely to avoid a 5xx / crash during a
  provider outage. It is disabled (never invoked) whenever the LLM call succeeds. Every entry
  it emits is tagged in `explanation` for auditability.
- **Overlapping directives of the same type** (e.g. two `solar_reduction` notes touching the
  same hour) are composed conservatively: `solar_reduction` factors multiply, and
  `minimum_battery_reserve` / `max_grid_window` take the most restrictive (max / min) value
  per hour. The Problem Statement does not specify this case explicitly; organizer-valid
  scenarios are stated not to require contradictory hard directives, so this is a defensive
  default rather than a documented contract requirement.
- **Infeasibility relaxation** (see "Optimizer & solver" above) only engages for malformed or
  adversarial input where directives are mutually infeasible; it should never trigger on a
  valid organizer scenario.
- No secrets, raw prompts containing secrets, or stack traces are ever included in API
  responses; unhandled errors return a generic `{"error": "internal_error"}` and log full
  detail server-side only.
- **Free-tier Groq rate limit.** The default free `on_demand` tier caps `openai/gpt-oss-120b`
  at 8000 tokens/minute (~6-8 interpretation calls/minute at this prompt size). A burst of
  requests beyond that returns HTTP 429 from Groq, which is treated the same as any other LLM
  outage: the deterministic fallback interpreter takes over for that request only (tagged in
  `explanation`), so the service still returns a valid 200 response rather than failing. Upgrade
  to a paid/dev tier on console.groq.com for higher throughput if sustained high request rates
  are expected during judging.

## Credits

Built with FastAPI, PuLP/CBC, and the Groq API (GPT-OSS 120B). Core architecture, prompt design,
guardrail logic, LP formulation, and validator are original work for this challenge.
