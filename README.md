# Call Insights API

**Live demo:** https://call-insights-console.vercel.app (free hosting: the first load can take up to a minute while the servers wake up)

A FastAPI backend that turns enterprise contact-centre call transcripts into structured insights with an LLM:
transcripts are submitted over a REST API, stored in **MongoDB**, queued in **Redis**, and analysed by a background
worker that prompts an LLM for **validated JSON**: a summary, intent, customer sentiment, promise-to-pay (amount
and date), whether to escalate, and action items. Results are cached in Redis and aggregated for reporting.

## Architecture
```
client ──POST /v1/calls──► FastAPI ──insert──► MongoDB (calls)
                              │
                              └──LPUSH──► Redis queue ──BRPOP──► worker ──prompt──► LLM (Gemini / offline rules)
                                                                   │  validate JSON (Pydantic); repair prompt if invalid
                                                                   └──► MongoDB (insights / error) ──► Redis cache on read
```

## API
| Method | Path | What it does |
| --- | --- | --- |
| POST | `/v1/calls` | Submit a transcript (validated); 202 queued, 409 duplicate `call_id`, 422 invalid input |
| GET | `/v1/calls` | List calls, newest first; filter by `status`, `intent`, `escalation` |
| GET | `/v1/calls/{call_id}/transcript` | The original transcript |
| GET | `/v1/calls/{call_id}` | Status (`queued` / `processing` / `done` / `failed`) and insights; served from Redis cache once done |
| POST | `/v1/calls/{call_id}/retry` | Re-queue a failed call |
| GET | `/v1/stats` | MongoDB aggregation: counts by status, intent, sentiment; escalation and promise-to-pay rates |
| GET | `/health` | MongoDB and Redis connectivity |

Interactive docs at `http://localhost:8000/docs` when running.

## Reliability choices
- **Structured output**: the prompt (`app/prompts.py`, versioned) specifies an exact JSON schema; every reply is
  validated with Pydantic (`app/schemas.py`). Invalid replies trigger a **repair prompt** carrying the validation error,
  up to 3 attempts; failures are recorded on the job, never crash the worker, and can be retried.
- **Async throughout**: FastAPI, Motor (async MongoDB), redis.asyncio and httpx for the LLM call.
- **Idempotent submission**: unique index on `call_id`; duplicates return 409.
- **Provider abstraction** (`app/llm.py`): Gemini over its REST API with JSON output mode, or an offline keyword
  baseline that needs no key (used in tests and CI).

## Evaluation
`scripts/evaluate.py` scores a provider on 34 labelled, fictional calls (banking, insurance, e-commerce):
a core set and a held-out hard set with paraphrases, Hinglish and indirect wording.

_Fill in after your run: baseline vs Gemini accuracy on the hard set._

## Run it
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                   # unit + API tests (in-memory MongoDB/Redis)
python scripts/evaluate.py                  # offline baseline
LLM_PROVIDER=gemini GEMINI_API_KEY=... python scripts/evaluate.py
```
With Docker: `cp .env.example .env && docker compose up --build`, then `python scripts/load_samples.py`.

CI (GitHub Actions) starts real MongoDB 7 and Redis 7 service containers and runs the full test suite, including an
end-to-end integration test, plus the offline evaluation.
