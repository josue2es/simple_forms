"""Application entry point: FastAPI + NiceGUI in a single process."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from nicegui import ui as nicegui_ui
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .api.router import require_api_key
from .api.router import router as api_router
from .config import settings
from .db import init_db
from .ratelimit import limiter

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("simple_forms")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Simple Forms started. Admin UI: /admin")
    if settings.master_api_key_is_generated:
        # Never log the full key — only a fingerprint for recognition.
        logger.info(
            "No SIMPLE_FORMS_MASTER_API_KEY set; generated one for this run "
            "(fingerprint: %s…). Set the env var for a stable key, or create "
            "named keys in the admin UI.",
            settings.master_api_key[:6],
        )
    yield


app = FastAPI(
    title="Simple Forms API",
    version="0.1.0",
    description="API to manage questionnaires and collect responses. "
    "Management endpoints require an API key (X-API-Key header).",
    lifespan=lifespan,
    # Disable the built-in docs; the OpenAPI schema is served explicitly
    # below, behind API-key auth.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Rate limiting (slowapi): keyed on the client's remote address.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(api_router, prefix="/api/v1")


@app.get("/api/v1/openapi.json", dependencies=[Depends(require_api_key)])
def openapi_schema():
    """Serve the OpenAPI schema to authenticated clients (docs UIs are disabled)."""
    return app.openapi()

# Importing the pages registers the NiceGUI routes via @ui.page decorators.
from .pages import admin, public  # noqa: E402, F401

nicegui_ui.run_with(app, title="Simple Forms", storage_secret=settings.storage_secret)
