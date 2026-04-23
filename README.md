# local-health-assistant

Local-first health assistant service.

## Current scope

This repository now contains:

- the version 1 design spec
- a Python service skeleton built around FastAPI
- SQLite bootstrap and local data-path management
- goal file loading and snapshotting
- message ingest for diet, hunger, and weight logs
- daily review and advice endpoints with rules-first logic
- manual Oura daily sync for sleep, readiness, and activity summaries

The service intentionally does not depend on CodexBridge in version 1. The first useful loop should stay deterministic and local: parse simple facts, store them, compare against goals, generate reviews, and record advice gaps. LLM-backed wording can be added later after the core data loop is stable.

## Repository layout

- `docs/specs/2026-04-11-local-health-assistant-design.md`
- `src/local_health_assistant/`
- `pyproject.toml`

## Local run

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Start the service:

```bash
python -m local_health_assistant
```

By default the service uses local paths under `data/health/`:

- SQLite: `data/health/health.db`
- Goals: `data/health/goals/current.yaml`
- Reviews: `data/health/daily_reviews/`
- Oura snapshots: `data/health/oura_snapshots/`

Override the data root if needed:

```bash
export LHA_DATA_DIR="/absolute/path/to/data/health"
```

## Oura setup

Create a Personal Access Token from Oura and set one of these environment variables before starting the service:

```bash
export OURA_ACCESS_TOKEN="your-token"
```

Accepted aliases:

- `OURA_ACCESS_TOKEN`
- `OURA_PERSONAL_ACCESS_TOKEN`
- `OURA_TOKEN`

Manual sync for a date:

```bash
curl -X POST http://127.0.0.1:8000/health/oura/sync \
  -H "Content-Type: application/json" \
  -d '{"target_date": "2026-04-22", "trigger_type": "manual"}'
```

The service stores the raw Oura response at `data/health/oura_snapshots/YYYY-MM-DD.json` and upserts normalized metrics into SQLite.

## Initial API surface

- `GET /health/status`
- `GET /health/goals`
- `PUT /health/goals`
- `POST /health/ingest/message`
- `POST /health/reviews/generate`
- `GET /health/reviews/{date}`
- `POST /health/advice/respond`
- `POST /health/oura/sync`
- `GET /health/oura/daily/{date}`

## Example ingest request

```bash
curl -X POST http://127.0.0.1:8000/health/ingest/message \
  -H "Content-Type: application/json" \
  -d '{
    "source_channel": "telegram",
    "source_user_id": "u1",
    "source_chat_id": "c1",
    "session_key": "health-chat-1",
    "text": "早餐两个蛋"
  }'
```
