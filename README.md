## WorkForYou – Milestone 1 (Deterministic Scheduler)

This project is a **deterministic, auditable scheduling backend** built with **FastAPI + SQLite**.

Gemini/LangChain are intentionally **not** part of Milestone 1’s core scheduling logic. The scheduler and validators are pure Python, driven by SQL data.

### What’s included in Milestone 1

- **2-week schedule generation** (`draft → review → redo → publish`)
- **Employees** with:
  - position hierarchy (`manager/shift_lead/regular`)
  - **category** (`server/cook/...`)
  - **job roles** (cashier/barista/…)
- **Job role coverage graph** (role_can_cover) with a **cached closure** for fast eligibility checks
- **Availability**
- **Time off requests** (PTO vs request off) with:
  - 14-day advance rule at submission
  - category-specific “keep ≥ X% available” capacity rule at approval
- **Metrics** derived deterministically from SQL (coverage + fairness)

---

## Setup

### 1) Create and activate virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Choose a database file (recommended)

By default the app uses `sqlite:///./workforyou.db`.

You can override with:

```bash
export DATABASE_URL="sqlite:///./workforyou.db"
```

SQLite DB files are ignored by git (`*.db`, `*.sqlite*`).

### 4) Run the server

```bash
uvicorn backend.main:app --reload
```

Open API docs:
- `http://localhost:8000/docs`

---

## Seed demo data (Milestone 1)

This creates a small restaurant-like dataset with 2 categories (server/cook), job roles, coverage edges, availability, and 2 weeks of shifts.

```bash
python -m backend.seed
```

Then generate a draft schedule in the API docs:
- `POST /schedules/generate` with body:

```json
{ "week_start_date": "2026-01-26" }
```

Optional actions after generation:
- Publish: `POST /schedules/{schedule_run_id}/publish`
- Redo (reason required): `POST /schedules/{schedule_run_id}/redo`
- Fairness charts: `GET /schedules/{schedule_run_id}/fairness-charts`
- Metrics: `GET /metrics/schedules/{schedule_run_id}`

---

## Simulation + baseline-vs-optimized analytics (Milestone 2)

Generate synthetic data and automatically produce **baseline + optimized** schedule runs for each 2-week period:

```bash
python -m backend.simulate --weeks 12 --seed 42
```

Then compare results over the same period-start range:

- `GET /analytics/summary?start=YYYY-MM-DD&end=YYYY-MM-DD&mode=baseline`
- `GET /analytics/summary?start=YYYY-MM-DD&end=YYYY-MM-DD&mode=optimized`
- `GET /analytics/compare?start=YYYY-MM-DD&end=YYYY-MM-DD`

Example (if simulation starts on a Monday `2026-02-09`):

```bash
curl "http://localhost:8000/analytics/compare?start=2026-02-09&end=2026-02-09"
```

---

## Environment knobs (useful during demos)

- **Time-off minimum availability ratio** (per category):

```bash
export TIME_OFF_MIN_AVAILABLE_RATIO=0.75
```

Meaning: keep at least 75% of employees in a category available on any date.

---

## Note about schema changes

We are not using migrations yet. If you add/rename DB columns while developing, delete your local SQLite file and restart:

```bash
rm -f workforyou.db
```

