"""Pydantic schemas for the REST API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionType = Literal["text", "textarea", "choice", "multi", "scale"]


class Question(BaseModel):
    id: str | None = None  # optional; auto-generated if omitted
    type: QuestionType = "text"
    label: str
    required: bool = False
    options: list[str] = Field(default_factory=list)  # for choice/multi
    min: int = 1  # for scale
    max: int = 5  # for scale
    help: str | None = None


class FormCreate(BaseModel):
    title: str
    description: str = ""
    access_code: str | None = None  # auto-generated if omitted
    questions: list[Question] = Field(default_factory=list)
    active: bool = True


class FormUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    access_code: str | None = None
    questions: list[Question] | None = None
    active: bool | None = None


class FormOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    description: str
    access_code: str
    questions: list[Question]
    active: bool
    created_at: datetime
    response_count: int = 0


class AnswerIn(BaseModel):
    question_id: str
    value: Any = None


class ResponseCreate(BaseModel):
    access_code: str
    answers: list[AnswerIn]


class ResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    form_id: int
    submitted_at: datetime
    answers: dict[str, Any]


class QuestionSummary(BaseModel):
    question_id: str
    label: str
    type: str
    answered: int
    skipped: int
    counts: dict[str, int] | None = None  # for choice/multi/scale


class FormSummary(BaseModel):
    form_id: int
    title: str
    total_responses: int
    questions: list[QuestionSummary]
