"""Database models (SQLModel)."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Form(SQLModel, table=True):
    """A questionnaire. Questions are stored as JSON for simple API round-trips."""

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    description: str = ""
    access_code: str = Field(index=True)
    questions: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class FormResponse(SQLModel, table=True):
    """One submission of a form. Answers are stored as {question_id: value} JSON."""

    __tablename__ = "form_response"

    id: int | None = Field(default=None, primary_key=True)
    form_id: int = Field(foreign_key="form.id", index=True)
    submitted_at: datetime = Field(default_factory=utcnow)
    answers: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class ApiKey(SQLModel, table=True):
    """A named API key for the REST API (hash stored, plaintext shown once)."""

    __tablename__ = "api_key"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    key_hash: str = Field(unique=True, index=True)
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None  # stamped on each successful verification
