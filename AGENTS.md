# Simple Forms — agent instructions

Python questionnaire webapp: NiceGUI UI + FastAPI REST API in **one process**,
architecture is a modular monolith with a shared service layer.
**Read the "Architecture" and "Data model" sections of README.md before making changes.**

## Key facts

- Layers: `app/pages/` (NiceGUI) and `app/api/` (REST) are thin; **all business
  logic lives in `app/service/`** and must not import from pages/api.
- NiceGUI pages call service functions directly (never the REST API).
- Domain errors = `ValueError`; API maps them to HTTP 400, UI shows via `ui.notify`.
- `Form.questions` and `FormResponse.answers` are **JSON columns**
  (questions: list of dicts with `id`/`type`/`label`/...; answers: `{question_id: value}`).
- Config and the DB engine are read **once at import** (`app/config.py`, `app/db.py`).

## Commands

This project uses [uv](https://docs.astral.sh/uv/) for environment and dependency
management (uv is the standard for all our Python projects). Dependencies are
locked in `uv.lock` — always commit lockfile changes, never edit it by hand.

```bash
uv sync --all-extras        # (re)create .venv and install locked deps
uv run uvicorn app.main:app --reload   # run dev server
uv run pytest                          # run tests (always run after changes)
```

## Rules

- Keep the service layer HTTP/UI-free.
- After any API or service change, run `pytest` — all tests must pass.
- Use one `Session(engine)` per request/page-handler; don't share sessions.
- SQLite = single process. Don't introduce multi-worker assumptions.
