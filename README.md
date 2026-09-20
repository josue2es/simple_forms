# Simple Forms

A small questionnaire webapp: create forms, share a **link + access code**, and let people answer.
Built as a **modular monolith (API-first)**:

- **NiceGUI** pages for the admin UI and public form answering — in one process.
- A **REST API** (`/api/v1`) with API-key auth, designed for **LLM agents** and scripts to manage forms.
- A pure-Python **service layer** shared by both UI and API (no HTTP hop).
- **SQLite** via SQLModel (swap to Postgres later if needed).

## Project layout

```
app/
  main.py           # FastAPI app + NiceGUI mount (single process)
  config.py         # env-based settings
  db.py             # engine / session
  models.py         # Form, FormResponse, ApiKey (SQLModel)
  service/          # domain logic: forms, responses, auth (no HTTP/UI deps)
  api/              # REST API routes + pydantic schemas (/api/v1)
  pages/            # NiceGUI pages (admin UI + public form page)
tests/              # API tests (pytest)
deploy/             # systemd unit (gitignored, server-specific)
```

## Architecture

Single process, three layers. **All business logic lives in `app/service/`**;
both the REST API and the NiceGUI pages are thin layers over it.

```
┌─────────────────────────────────────────────────────┐
│                uvicorn (one process)                │
│                                                     │
│  NiceGUI pages (app/pages/)     REST API (/api/v1)  │
│    /admin  — admin UI            app/api/router.py  │
│    /f/{slug} — public forms      (API-key auth)     │
│         │                              │            │
│         │  direct Python calls        │ direct      │
│         │  (NO HTTP hop)              │ Python calls│
│         ▼                              ▼            │
│             app/service/  (domain logic)             │
│             forms.py  responses.py  auth.py         │
│                         │                           │
│                         ▼                           │
│             SQLModel → SQLite (app/models.py)       │
└─────────────────────────────────────────────────────┘
```

**Rules of the codebase:**

- `service/` must not import from `api/` or `pages/` (keep it dependency-free).
- Domain errors are plain `ValueError` with human-readable messages; the API
  layer maps them to HTTP 400, UI pages show them via `ui.notify`.
- NiceGUI pages never call the REST API — they import and call service
  functions with their own SQLModel session (`Session(engine)`).
- API routes in `app/api/router.py` stay thin: auth + get-or-404 + call service
  + serialize via schemas in `app/api/schemas.py`.
- NiceGUI pages register via `@ui.page(...)` decorators **at import time**;
  `main.py` imports `app.pages` for their side effects only.

### Data model

| Table | Key fields | Notes |
|---|---|---|
| `Form` | `slug`, `access_code`, `questions` (JSON), `active` | `questions` is a JSON list of question dicts (see below); `slug` is unique, used in `/f/{slug}` and in the public submission URL |
| `FormResponse` | `form_id`, `answers` (JSON), `submitted_at` | `answers` is `{question_id: value}` — value is a string (text/textarea/choice), a list of strings (multi), or an int (scale) |
| `ApiKey` | `name`, `key_hash` (sha256), `active`, `last_used_at` | plaintext is shown once at creation, never stored; `last_used_at` is stamped on each successful verification so unused keys are visible and revocable |

Normalized question dict (produced by `service/forms.py:normalize_questions`, which also auto-assigns `id` like `q1`, `q2`, ... and validates everything):

```json
{"id": "q1", "type": "scale", "label": "Rating", "required": false,
 "options": ["..."], "min": 1, "max": 5, "help": "optional"}
```

### Example: adding a new question type

To add e.g. a `date` type, touch exactly these places:

1. `service/forms.py` — add to `QUESTION_TYPES` + normalization in `normalize_questions()`
2. `service/responses.py` — validation branch in `validate_answers()`
3. `pages/public.py` — input widget in `_render_question()`
4. `pages/admin.py` — nothing (type dropdown is generic), unless it needs extra fields
5. `api/schemas.py` — extend the `QuestionType` literal
6. `tests/test_api.py` — add a case

### Gotchas

- Config/env vars are read **once at import time** (`app/config.py`). Tests must
  set `SIMPLE_FORMS_DB` before importing `app` (see `tests/conftest.py`).
- The DB engine is also created at import time; changing `SIMPLE_FORMS_DB`
  requires a process restart.
- Access-code checks are case-insensitive and constant-time (`service/responses.py:check_access_code`); generated codes are 10 characters from an unambiguous alphabet.
- Deleting a form deletes its responses (`service/forms.py:delete_form`).
- Rate limits (per client IP, via slowapi): response submission is limited to
  10/minute, admin login attempts to 5/minute. Client IPs require
  `--proxy-headers --forwarded-allow-ips=127.0.0.1` on uvicorn behind a reverse
  proxy (already set in `deploy/simple-forms.service`), otherwise every request
  appears to come from 127.0.0.1.
- SQLite means one process only (already how the app runs). Multi-worker
  deployment would need Postgres + revisiting `Session(engine)` usage in pages.

## Quickstart

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.
Dependencies are pinned in `uv.lock` (committed to git) for reproducible setups.

```bash
uv sync --all-extras          # creates .venv and installs locked dependencies
uv run uvicorn app.main:app --reload
```

(No activation needed — `uv run` executes commands in the project's `.venv`.
If you don't have uv yet: `curl -LsSf https://astral.sh/uv/install.sh | sh`.)

- **Admin UI:** http://localhost:8000/admin — password from
  `SIMPLE_FORMS_ADMIN_PASSWORD` (**required** — the app refuses to start with
  the default `admin`).
- **OpenAPI schema (needs API key):** http://localhost:8000/api/v1/openapi.json
  (interactive Swagger/ReDoc UIs are disabled)

## Configuration (environment variables)

Variables are read from the environment; a **`.env`** file in the project root is
loaded automatically if present (real environment variables always win).
Copy `.env.example` to `.env` and fill in your values — **never commit `.env` to git**.

```bash
cp .env.example .env
# generate a stable master API key:
uv run python -c "import secrets; print('sfk_' + secrets.token_urlsafe(24))"
```

| Variable | Default | Description |
|---|---|---|
| `SIMPLE_FORMS_DB` | `forms.db` | SQLite database file path |
| `SIMPLE_FORMS_BASE_URL` | *(unset)* | Public base URL for full share links (e.g. `http://10.0.0.5:8000`) |
| `SIMPLE_FORMS_ADMIN_PASSWORD` | *(none)* | **Required.** Password for the admin UI; the app refuses to start if unset or `admin` |
| `SIMPLE_FORMS_MASTER_API_KEY` | random (only a 6-char fingerprint logged) | Stable master API key |
| `SIMPLE_FORMS_STORAGE_SECRET` | random | Secret for browser session storage |

> **Important:** always set `SIMPLE_FORMS_MASTER_API_KEY` explicitly (in `.env` or
> your process manager). Otherwise a random key is generated per restart, which
> breaks any saved keys in LLM agents or scripts.

In production, prefer keeping secrets outside the repo entirely, e.g. a systemd
unit with `EnvironmentFile=/etc/simple_forms.env`.

## How to use

1. Log into `/admin`, create a form, add questions, save.
2. Click the **share** icon to get the public link (`/f/<slug>`) and access code.
3. Send link + code to people; they answer in the browser.
4. View responses (and export CSV) from the form's **responses** page.

### Question types

| Type | JSON fields | Answer format |
|---|---|---|
| `text` | `label`, `required`, `help` | string |
| `textarea` | same | string |
| `choice` | + `options: []` | one option (string) |
| `multi` | + `options: []` | list of options |
| `scale` | + `min`, `max` | integer within bounds |

## REST API (for LLMs / scripts)

All management endpoints need the `X-API-Key` header. Use the master key
(`SIMPLE_FORMS_MASTER_API_KEY`) or create named keys in the admin UI (**API Keys** tab).
Invalid keys get a **404** (not 401/403) so routes and form IDs can't be enumerated.
The one public endpoint is response submission, which needs the form's access code
instead and is addressed by the form's **slug** (not its numeric id).

```bash
# Create a form (questions are a list; ids are auto-generated if omitted)
curl -s -X POST http://localhost:8000/api/v1/forms \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{
    "title": "Team pulse check",
    "questions": [
      {"type": "text", "label": "Your name", "required": true},
      {"type": "scale", "label": "How is your week going?", "min": 1, "max": 5},
      {"type": "choice", "label": "Preferred day for retro", "options": ["Mon", "Tue", "Fri"]}
    ]
  }'

# List forms / get one
curl -s http://localhost:8000/api/v1/forms -H "X-API-Key: $KEY"

# Submit a response (public — needs the access code, not an API key;
# keyed on the slug; rate-limited to 10/minute per IP)
curl -s -X POST http://localhost:8000/api/v1/forms/team-pulse-check/responses \
  -H "Content-Type: application/json" \
  -d '{"access_code": "AB3X9KQ2RH", "answers": [
        {"question_id": "q1", "value": "Alice"},
        {"question_id": "q2", "value": 4},
        {"question_id": "q3", "value": "Fri"}]}'

# Get all responses (JSON), or CSV
curl -s http://localhost:8000/api/v1/forms/1/responses -H "X-API-Key: $KEY"
curl -s http://localhost:8000/api/v1/forms/1/responses.csv -H "X-API-Key: $KEY"

# Aggregate summary (per-question counts)
curl -s http://localhost:8000/api/v1/forms/1/summary -H "X-API-Key: $KEY"
```

### LLM integration

Point your LLM/agent at the **OpenAPI schema** (`/api/v1/openapi.json` — also
requires the `X-API-Key` header; the built-in Swagger/Redoc UIs are disabled),
give it an API key (create a named key per agent so you can revoke it
independently), and it can fully manage forms: create, edit, close, and analyze
questionnaires via the endpoints above.

## Tests

```bash
uv sync --all-extras   # ensures dev dependencies (pytest, httpx) are installed
uv run pytest
```

## Run in production

Put it behind a reverse proxy (nginx/caddy) for TLS. For a stable API key across restarts,
always set `SIMPLE_FORMS_MASTER_API_KEY` (or use DB-stored named keys).

### Run as a systemd service

A ready-made unit file lives at `deploy/simple-forms.service` (gitignored, since it
contains server-specific paths). The equivalent setup:

```ini
# /etc/systemd/system/simple-forms.service
[Unit]
Description=Simple Forms (NiceGUI + FastAPI questionnaire app)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/simple_forms
EnvironmentFile=-/home/ubuntu/simple_forms/.env
ExecStart=/home/ubuntu/simple_forms/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
uv sync --all-extras   # creates .venv with the locked dependencies
sudo cp deploy/simple-forms.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now simple-forms

systemctl status simple-forms        # check it's running
journalctl -u simple-forms -f        # follow logs
```

Before enabling, create your `.env` with a fixed `SIMPLE_FORMS_MASTER_API_KEY`
(see [Configuration](#configuration-environment-variables)) so the API key
survives restarts.
