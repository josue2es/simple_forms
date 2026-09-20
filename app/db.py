"""Database engine, session factory and initialization."""

from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (import registers all models)
from .config import settings

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Tiny SQLite migrations for pre-existing databases (no Alembic yet)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(api_key)")]
        if cols and "last_used_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE api_key ADD COLUMN last_used_at TIMESTAMP")


def get_session():
    with Session(engine) as session:
        yield session
