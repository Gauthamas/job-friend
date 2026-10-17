# Job-Friend — repo map

Local app: resume → reviewable inventory of experience units → requirements matched
against a job description → a cover letter the user writes by hand. No generated prose —
every model output is structured data the user reviews; letter text is always typed,
joined verbatim.

## Principles

1. No generated prose — model outputs are structured data only.
2. Model proposes, user reviews — every extraction is editable before it is trusted.
3. No fabrication — a claimed match must cite a real unit id; code rejects the rest.
4. Gaps are normal — a requirement with no match is a valid, expected result.
5. Everything local — no network calls except to the local model server (LM Studio).

## Stack and ports

FastAPI (Python 3.11+, stdlib `sqlite3`) + SvelteKit (SPA, `adapter-static`) + Tailwind.
Model calls go through the `openai` SDK to a local LM Studio server — one model loads
at a time, calls are sequential, never parallel.

| What | Port |
|---|---|
| Backend (FastAPI) | 8001 |
| Frontend (SvelteKit dev) | 5500 |
| LM Studio server | 1234 |

Single-process mode (`npm run build`, then run the backend) serves everything from 8001.

## Running

```powershell
cd backend; python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"; uvicorn app.main:app --port 8001
```
```powershell
cd frontend; npm install; npm run dev
```

Tests (mock LLM client, no model server needed):
```powershell
cd backend; .venv\Scripts\Activate.ps1; pytest -q
cd frontend; npm run check
```

On-demand fixtures that DO need LM Studio running (not part of the default suite):
`python scripts/check_extraction_regression.py`, `python scripts/benchmark.py`.
Any change to the extraction prompt (`REQUIREMENT_EXTRACT` in `backend/app/llm/tasks.py`)
must be re-run against `check_extraction_regression.py`.

## Pipeline stages — where each lives

| Stage | Backend | Frontend route |
|---|---|---|
| Inventory import | `routers/inventories.py`, `llm/incremental_resume_parser.py` | `/inventories/new`, `/inventories/review` |
| Enrichment + skills | `routers/jobs.py` (`get_enrichment`), `routers/units.py` | `/jobs/[id]/enrichment` |
| JD submit + extraction | `routers/jobs.py` (`_run_extraction`) | `/jobs/[id]` |
| Review | `routers/requirements.py` | `/jobs/[id]` |
| Shortlisting | `shortlist.py`, `scoring.py` | automatic, no screen |
| Judging (20-min window) | `judging.py` | `/jobs/[id]` |
| Pair builder | `pairing.py`, `routers/pairs.py` | automatic, no screen |
| Statements | `statements.py`, `routers/statements.py` | `/jobs/[id]/statements` |
| Threads (propose/assign/verify) | `threads.py`, `llm/thread_validation.py` | `/jobs/[id]/threads` |
| Primary/secondary thread | `thread_ranking.py`, `routers/primary_secondary.py` | `/jobs/[id]/primary-secondary` |
| Writing view + Generate | `letter.py`, `routers/letter.py` | `/jobs/[id]/write` |

## The six chat-model calls

All defined as `TaskProfile`s in `backend/app/llm/tasks.py`:

| Task | Temp | Max tokens | Input → output |
|---|---|---|---|
| `resume_structure` | 0 | 3000 | resume text → roles + bullets |
| `requirement_extract` | 0 | 2000 | JD text → requirements + weights |
| `judge_batch` | 0 | setting (`judge_max_tokens`) | ≤N requirements + candidates → per-unit verdicts |
| `propose_threads` | 0.2 | setting | all written statements → candidate threads |
| `assign_unused` | 0.2 | setting | one leftover statement → a thread or none |
| `verify_thread` | 0.2 | setting | one thread idea + one unit → verdict + quote |

A separate embedding model (no `TaskProfile`, no temperature/thinking concept) backs
shortlisting, unit search, and pair scoring — not one of the six above.

## Repo layout

```
job-friend/
  backend/app/       FastAPI app, routers, judging/pairing/threads/letter logic
  backend/app/llm/    task definitions, LM Studio client, validation
  backend/app/migrations/  one .sql file per schema change, applied in order at startup
  backend/tests/      pytest, mock LLM client, no model server needed
  backend/prompts/    prompt text for the three thread-discovery tasks
  frontend/src/       SvelteKit app (SPA)
  fixtures/           sample resume/JD fixtures used by tests and the benchmark
  scripts/            benchmark.py, check_extraction_regression.py
  demo/               drop a demo resume + JD here to try the app end to end
```

Changes spanning API and UI go in the same commit.
