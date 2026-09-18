# GridWise Optimizer — Submission Package

Everything required by the Participant Guide (Sec. 02, "Submission package"), ready to
copy-paste into the organizers' submission form.

---

## 1. Working public endpoint

```
https://gridwise-optimizer.onrender.com
```

- `GET  https://gridwise-optimizer.onrender.com/health`
- `POST https://gridwise-optimizer.onrender.com/optimize-energy`

No login, VPN, or dashboard access required. Verified: 10/10 public samples pass end-to-end
with the real LLM, p95 latency 1.88s (well under the 5s tier). A GitHub Actions workflow
(`.github/workflows/keep-alive.yml`) pings `/health` every 5 minutes so the service never
idles out during the judging window.

---

## 2. GitHub repository

```
https://github.com/Iftiak-Ahmed/GridWise
```

> ⚠️ **Action needed before the round starts:** this repo must be **private** during the event
> and switched to **public** only after the submission deadline (Settings → General → Danger
> Zone → Change visibility). It is currently public — flip it to private before/at round start.

---

## 3. README & configuration

README is at the repository root: [`README.md`](README.md). It includes local quickstart,
required environment-variable names, model/provider (Groq GPT-OSS 120B primary, Gemini 3.1
Flash-Lite secondary fallback), LLM role, guardrails, optimizer/solver (PuLP + CBC), exact run
command, `/health` and `/optimize-energy` curl examples, public-sample test command,
dependencies, and known limitations. No secret values are committed.

Required environment variables (see `.env.example`):

| Variable | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes | Primary LLM — free at console.groq.com/keys |
| `GROQ_MODEL` | No (default `openai/gpt-oss-120b`) | |
| `GEMINI_API_KEY` | No (recommended) | Secondary LLM fallback — free at aistudio.google.com/apikey |
| `GEMINI_MODEL` | No (default `gemini-3.1-flash-lite`) | |
| `GROQ_TIMEOUT_SECONDS` | No (default `5`) | |
| `GEMINI_TIMEOUT_SECONDS` | No (default `15`) | |
| `PORT` | No (default `8000`) | |

---

## 4. Docker fallback image

```
docker pull turzaiftiak/gridwise-optimizer:latest
```

- **Digest:** `sha256:d05ee9cc626bf4c9f6b1d77feb0267a991ae684821137782f03bf6d78f4a1231`
- **Registry:** Docker Hub
- **Exposed port:** `8000` (binds `0.0.0.0:${PORT}`)
- **No baked-in secrets** — keys are injected at `docker run` time.

Verified `docker run` command:

```bash
docker run --rm -p 8000:8000 \
  -e GROQ_API_KEY=your_groq_key_here \
  -e GROQ_MODEL=openai/gpt-oss-120b \
  -e GEMINI_API_KEY=your_gemini_key_here \
  -e GEMINI_MODEL=gemini-3.1-flash-lite \
  turzaiftiak/gridwise-optimizer:latest

curl http://localhost:8000/health
# {"status":"ok"}
```

---

## 5. 3-minute architecture / solution video

> ❌ **Not yet recorded.** Maximum 3 minutes; must explain the problem, architecture overview,
> LLM → deterministic guardrails → optimizer flow, and how the submission is run/tested
> (Participant Guide Sec. 02/08). Tie-break only — no base-score impact, but it is the
> **first** tie-break criterion, so worth doing properly.
>
> Link once recorded: `_________________________`

---

## Quick pre-submit checklist (Participant Guide Sec. 11)

- [x] `GET /health` reachable, returns `{"status":"ok"}`
- [x] `POST /optimize-energy` reachable externally, accepts 1–3 `operator_notes`
- [x] Every note → exactly one `directive_interpretation` entry, correct `applies`/`no_op` semantics
- [x] LLM output deterministically guardrailed before optimization
- [x] `hourly_plan` obeys ground-truth directives + all GridWise energy/battery rules
- [x] `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh` match `hourly_plan` recalculation
- [x] README self-contained with clean local quickstart, no committed secrets
- [ ] Repository private during the event (⚠️ currently public — fix before round start)
- [x] Docker fallback image pullable, exact digest recorded, `/health` verified
- [ ] 3-minute video recorded and accessible
