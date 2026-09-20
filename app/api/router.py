"""REST API routes (/api/v1).

Management endpoints require an API key (X-API-Key header): either the master
key (env SIMPLE_FORMS_MASTER_API_KEY) or a named key created in the admin UI.
Public submission only requires the form's access code.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlmodel import Session, select

from ..db import get_session
from ..models import Form, FormResponse
from ..ratelimit import limiter
from ..service import auth as auth_service
from ..service import forms as forms_service
from ..service import responses as responses_service
from .schemas import (
    FormCreate,
    FormOut,
    FormSummary,
    FormUpdate,
    Question,
    QuestionSummary,
    ResponseCreate,
    ResponseOut,
)

router = APIRouter()


async def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    session: Session = Depends(get_session),
) -> Session:
    # 404 (not 401/403) so that management routes and form IDs are not
    # enumerable by probing with invalid keys.
    if not auth_service.verify_api_key(session, x_api_key):
        raise HTTPException(status_code=404, detail="Not Found")
    return session


def _get_form_or_404(session: Session, form_id: int) -> Form:
    form = forms_service.get_form(session, form_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


def _get_form_by_slug_or_404(session: Session, slug: str) -> Form:
    form = forms_service.get_form_by_slug(session, slug)
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


def _form_out(session: Session, form: Form) -> FormOut:
    count = session.exec(select(func.count(FormResponse.id)).where(FormResponse.form_id == form.id)).one()
    out = FormOut.model_validate(form)
    out.response_count = count
    return out


@router.get("/forms", response_model=list[FormOut])
def list_forms(session: Session = Depends(require_api_key)):
    return [_form_out(session, f) for f in forms_service.list_forms(session)]


@router.post("/forms", response_model=FormOut, status_code=201)
def create_form(payload: FormCreate, session: Session = Depends(require_api_key)):
    try:
        form = forms_service.create_form(
            session,
            title=payload.title,
            description=payload.description,
            access_code=payload.access_code,
            questions=[q.model_dump() for q in payload.questions],
            active=payload.active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _form_out(session, form)


@router.get("/forms/{form_id}", response_model=FormOut)
def get_form(form_id: int, session: Session = Depends(require_api_key)):
    return _form_out(session, _get_form_or_404(session, form_id))


@router.patch("/forms/{form_id}", response_model=FormOut)
def update_form(form_id: int, payload: FormUpdate, session: Session = Depends(require_api_key)):
    form = _get_form_or_404(session, form_id)
    fields = payload.model_dump(exclude_unset=True)
    if "questions" in fields and fields["questions"] is not None:
        fields["questions"] = [q if isinstance(q, dict) else q.model_dump() for q in fields["questions"]]
    try:
        form = forms_service.update_form(session, form, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _form_out(session, form)


@router.delete("/forms/{form_id}", status_code=204)
def delete_form(form_id: int, session: Session = Depends(require_api_key)):
    form = _get_form_or_404(session, form_id)
    forms_service.delete_form(session, form)


@router.post("/forms/{slug}/responses", response_model=ResponseOut, status_code=201)
@limiter.limit("10/minute")
def submit_response(slug: str, request: Request, payload: ResponseCreate, session: Session = Depends(get_session)):
    """Public endpoint: submit a response using the form's access code.

    Keyed on the form's slug (not the sequential DB id) so form ids are not
    enumerable; rate-limited per IP so access codes can't be brute-forced.
    """
    form = _get_form_by_slug_or_404(session, slug)
    if not responses_service.check_access_code(form, payload.access_code):
        raise HTTPException(status_code=403, detail="Invalid access code")
    try:
        resp = responses_service.submit_response(
            session, form, [a.model_dump() for a in payload.answers]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return resp


@router.get("/forms/{form_id}/responses", response_model=list[ResponseOut])
def list_responses(form_id: int, session: Session = Depends(require_api_key)):
    _get_form_or_404(session, form_id)
    return responses_service.list_responses(session, form_id)


@router.get("/forms/{form_id}/responses.csv", response_class=PlainTextResponse)
def responses_csv(form_id: int, session: Session = Depends(require_api_key)):
    form = _get_form_or_404(session, form_id)
    csv_text = responses_service.responses_to_csv(form, responses_service.list_responses(session, form_id))
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="form_{form_id}_responses.csv"'},
    )


@router.get("/forms/{form_id}/summary", response_model=FormSummary)
def form_summary(form_id: int, session: Session = Depends(require_api_key)):
    form = _get_form_or_404(session, form_id)
    responses = responses_service.list_responses(session, form_id)

    questions: list[QuestionSummary] = []
    for q in form.questions:
        item = QuestionSummary(
            question_id=q["id"], label=q["label"], type=q["type"], answered=0, skipped=0
        )
        if q["type"] in ("choice", "multi", "scale"):
            item.counts = {}
        for r in responses:
            v = r.answers.get(q["id"])
            filled = v not in (None, "", [])
            if filled:
                item.answered += 1
                if item.counts is not None:
                    for x in (v if isinstance(v, list) else [v]):
                        key = str(x)
                        item.counts[key] = item.counts.get(key, 0) + 1
            else:
                item.skipped += 1
        questions.append(item)

    return FormSummary(form_id=form.id, title=form.title, total_responses=len(responses), questions=questions)
