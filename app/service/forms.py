"""Form/questionnaire management (domain layer)."""

import re
import secrets

from sqlmodel import Session, select

from ..models import Form

QUESTION_TYPES = ("text", "textarea", "choice", "multi", "scale")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no easily-confused characters
_CODE_LENGTH = 10  # ~50 bits of entropy: not brute-forceable through the rate-limited endpoint


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "form"


def generate_access_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _unique_slug(session: Session, title: str) -> str:
    base = slugify(title)
    slug = base
    while session.exec(select(Form).where(Form.slug == slug)).first() is not None:
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def normalize_questions(questions) -> list[dict]:
    """Validate and normalize a list of question dicts. Raises ValueError."""
    result: list[dict] = []
    seen: set[str] = set()
    for i, q in enumerate(questions or [], start=1):
        if hasattr(q, "model_dump"):
            q = q.model_dump()
        q = dict(q or {})

        qtype = q.get("type", "text")
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"question {i}: unknown type '{qtype}' (allowed: {', '.join(QUESTION_TYPES)})")

        label = str(q.get("label", "")).strip()
        if not label:
            raise ValueError(f"question {i}: label is required")

        qid = str(q.get("id") or "").strip()
        if not qid:
            qid = f"q{i}"
            n = 0
            while qid in seen:
                n += 1
                qid = f"q{i}_{n}"
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", qid):
            raise ValueError(f"question {i}: invalid id '{qid}' (use letters, digits, '-', '_')")
        if qid in seen:
            raise ValueError(f"question {i}: duplicate question id '{qid}'")
        seen.add(qid)

        entry = {"id": qid, "type": qtype, "label": label, "required": bool(q.get("required", False))}

        if qtype in ("choice", "multi"):
            options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
            if not options:
                raise ValueError(f"question '{label}': choice/multi questions require at least one option")
            entry["options"] = options
        elif qtype == "scale":
            entry["min"] = int(q.get("min", 1))
            entry["max"] = int(q.get("max", 5))
            if entry["max"] <= entry["min"]:
                raise ValueError(f"question '{label}': scale max must be greater than min")

        if q.get("help"):
            entry["help"] = str(q["help"])

        result.append(entry)
    return result


def create_form(
    session: Session,
    *,
    title: str,
    description: str = "",
    access_code: str | None = None,
    questions=None,
    active: bool = True,
) -> Form:
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    code = (access_code or generate_access_code()).strip()
    if not code:
        raise ValueError("access code must not be empty")
    form = Form(
        slug=_unique_slug(session, title),
        title=title,
        description=description or "",
        access_code=code,
        questions=normalize_questions(questions),
        active=active,
    )
    session.add(form)
    session.commit()
    session.refresh(form)
    return form


def get_form(session: Session, form_id: int) -> Form | None:
    return session.get(Form, form_id)


def get_form_by_slug(session: Session, slug: str) -> Form | None:
    return session.exec(select(Form).where(Form.slug == slug)).first()


def list_forms(session: Session) -> list[Form]:
    return list(session.exec(select(Form).order_by(Form.created_at.desc())))


def update_form(session: Session, form: Form, *, title=None, description=None, access_code=None, questions=None, active=None) -> Form:
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("title must not be empty")
        form.title = title
    if description is not None:
        form.description = description
    if access_code is not None:
        access_code = access_code.strip()
        if not access_code:
            raise ValueError("access code must not be empty")
        form.access_code = access_code
    if questions is not None:
        form.questions = normalize_questions(questions)
    if active is not None:
        form.active = active
    session.add(form)
    session.commit()
    session.refresh(form)
    return form


def delete_form(session: Session, form: Form) -> None:
    from sqlmodel import select as _select

    from ..models import FormResponse

    for resp in session.exec(_select(FormResponse).where(FormResponse.form_id == form.id)):
        session.delete(resp)
    session.delete(form)
    session.commit()
