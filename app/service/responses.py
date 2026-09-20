"""Response submission, validation and export (domain layer)."""

import csv
import io
import secrets

from sqlmodel import Session, select

from ..models import Form, FormResponse


def check_access_code(form: Form, code: str) -> bool:
    """Case-insensitive, constant-time access code check."""
    given = (code or "").strip().upper()
    expected = (form.access_code or "").strip().upper()
    return secrets.compare_digest(given, expected)


def _answer_map(answers) -> dict:
    """Accept a list of {question_id, value} dicts or a plain {qid: value} mapping."""
    if isinstance(answers, dict):
        return dict(answers)
    result: dict = {}
    for a in answers or []:
        if hasattr(a, "model_dump"):
            a = a.model_dump()
        qid = (a or {}).get("question_id")
        if qid:
            result[qid] = a.get("value")
    return result


def validate_answers(form: Form, answers) -> dict:
    """Validate answers against the form's questions. Returns {qid: value} or raises ValueError."""
    questions = {q["id"]: q for q in form.questions}
    values = _answer_map(answers)
    errors: list[str] = []
    clean: dict = {}

    for qid in values:
        if qid not in questions:
            errors.append(f"unknown question id: '{qid}'")

    for q in form.questions:
        qid, label = q["id"], q["label"]
        qtype, required = q["type"], q.get("required", False)
        v = values.get(qid)

        if qtype in ("text", "textarea"):
            v = v.strip() if isinstance(v, str) else (v if v is not None else "")
            if required and not v:
                errors.append(f"'{label}' is required")
            clean[qid] = v

        elif qtype == "choice":
            if v in (None, ""):
                if required:
                    errors.append(f"'{label}' is required")
                clean[qid] = None
            elif v not in q.get("options", []):
                errors.append(f"'{label}': '{v}' is not a valid option")
                clean[qid] = v
            else:
                clean[qid] = v

        elif qtype == "multi":
            if v is None:
                v = []
            elif not isinstance(v, list):
                v = [v]
            if required and not v:
                errors.append(f"'{label}' is required")
            bad = [x for x in v if x not in q.get("options", [])]
            if bad:
                errors.append(f"'{label}': invalid option(s): {', '.join(map(str, bad))}")
            clean[qid] = v

        elif qtype == "scale":
            if v in (None, ""):
                if required:
                    errors.append(f"'{label}' is required")
                clean[qid] = None
            else:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    errors.append(f"'{label}': value must be a number")
                else:
                    if not (q.get("min", 1) <= v <= q.get("max", 5)):
                        errors.append(f"'{label}': value must be between {q.get('min', 1)} and {q.get('max', 5)}")
                    clean[qid] = v

    if errors:
        raise ValueError("; ".join(errors))
    return clean


def submit_response(session: Session, form: Form, answers) -> FormResponse:
    if not form.active:
        raise ValueError("this form is closed and no longer accepts responses")
    clean = validate_answers(form, answers)
    resp = FormResponse(form_id=form.id, answers=clean)
    session.add(resp)
    session.commit()
    session.refresh(resp)
    return resp


def list_responses(session: Session, form_id: int) -> list[FormResponse]:
    stmt = select(FormResponse).where(FormResponse.form_id == form_id).order_by(FormResponse.submitted_at.desc())
    return list(session.exec(stmt))


def format_answer(value) -> str:
    if value is None or value == "" or value == []:
        return "(no answer)"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def responses_to_csv(form: Form, responses: list[FormResponse]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["response_id", "submitted_at"] + [q["label"] for q in form.questions])
    for r in responses:
        row = [r.id, r.submitted_at.isoformat()]
        for q in form.questions:
            row.append(format_answer(r.answers.get(q["id"])).replace("(no answer)", ""))
        writer.writerow(row)
    return buf.getvalue()
