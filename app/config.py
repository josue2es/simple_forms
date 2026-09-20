"""Application settings, loaded from environment variables."""

import os
import secrets

from dotenv import load_dotenv

# Load a .env file from the project root (or parents) if present.
# Existing environment variables always win over .env values.
load_dotenv()


class Settings:
    def __init__(self) -> None:
        # SQLite database file path.
        self.db_path: str = os.environ.get("SIMPLE_FORMS_DB", "forms.db")

        # Password for the NiceGUI admin UI. Refuse to start with the insecure
        # default: this must be set explicitly via the environment or .env.
        admin_password = (os.environ.get("SIMPLE_FORMS_ADMIN_PASSWORD") or "").strip()
        if not admin_password or admin_password == "admin":
            raise RuntimeError(
                "SIMPLE_FORMS_ADMIN_PASSWORD is not set (or still the default 'admin'). "
                "Set a real password in the environment or .env — refusing to start."
            )
        self.admin_password: str = admin_password

        # Public base URL of the app (e.g. "http://192.168.1.10:8000"). Used to
        # build full shareable links in the admin UI. If unset, links are shown
        # relative to the host the admin UI is opened from.
        self.base_url: str = os.environ.get("SIMPLE_FORMS_BASE_URL", "").rstrip("/")

        # Master API key for the REST API. If not set via env, a random one is
        # generated per process (logged at startup). Named keys stored in the
        # database are stable across restarts.
        env_key = os.environ.get("SIMPLE_FORMS_MASTER_API_KEY")
        self.master_api_key: str = env_key or ("sfk_" + secrets.token_urlsafe(24))
        self.master_api_key_is_generated: bool = not env_key

        # Secret for NiceGUI browser storage (admin session).
        self.storage_secret: str = os.environ.get("SIMPLE_FORMS_STORAGE_SECRET") or secrets.token_urlsafe(32)


settings = Settings()
