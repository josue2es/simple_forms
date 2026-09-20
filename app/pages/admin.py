"""NiceGUI admin pages: form management, responses viewer, API keys."""

import json
import secrets
import tempfile

from limits import parse
from nicegui import context, ui, app
from sqlalchemy import func
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import FormResponse
from ..ratelimit import get_remote_address, limiter
from ..service import auth as auth_service
from ..service import forms as forms_service
from ..service import responses as responses_service

QUESTION_TYPES = list(forms_service.QUESTION_TYPES)

# Per-IP budget for admin login attempts (shared with the REST API limiter storage).
_LOGIN_LIMIT = parse("5/minute")


def _hit_login_limit() -> bool:
    """Count one login attempt against the per-IP rate limit. True if exceeded."""
    try:
        request = context.client.request
    except Exception:
        request = None
    ip = get_remote_address(request) if request is not None else "unknown"
    return not limiter.limiter.hit(_LOGIN_LIMIT, ip)


def _is_authenticated() -> bool:
    return bool(app.storage.user.get("authenticated"))


def _session() -> Session:
    return Session(engine)


def _response_count(session: Session, form_id: int) -> int:
    return session.exec(select(func.count(FormResponse.id)).where(FormResponse.form_id == form_id)).one()


# ---------------------------------------------------------------- login


@ui.page("/admin/login", title="Admin — Simple Forms")
def login_page():
    if _is_authenticated():
        ui.navigate.to("/admin")
        return
    with ui.column().classes("max-w-xs mx-auto pt-24 items-center gap-4"):
        ui.label("Simple Forms").classes("text-2xl font-bold")
        ui.label("Admin login").classes("text-sm text-gray-500")
        password = ui.input("Admin password", password=True, password_toggle_button=True).classes("w-full")

        def try_login():
            if _hit_login_limit():
                ui.notify("Too many login attempts — wait a minute and try again", type="negative")
                return
            if secrets.compare_digest(password.value or "", settings.admin_password):
                app.storage.user["authenticated"] = True
                ui.navigate.to("/admin")
            else:
                ui.notify("Wrong password", type="negative")

        password.on("keydown.enter", try_login)
        ui.button("Log in", on_click=try_login).classes("w-full")


@ui.page("/admin", title="Admin — Simple Forms")
def admin_page():
    if not _is_authenticated():
        ui.navigate.to("/admin/login")
        return
    _render_admin()


def _render_admin():
    with ui.column().classes("w-full max-w-4xl mx-auto p-6 gap-2"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Simple Forms").classes("text-2xl font-bold")
            ui.button("Log out", on_click=_logout).props("outline")

        with ui.tabs() as tabs:
            ui.tab("forms", label="Forms", icon="list_alt")
            ui.tab("keys", label="API Keys", icon="key")
        with ui.tab_panels(tabs, value="forms").classes("w-full"):
            with ui.tab_panel("forms"):
                _render_forms_tab()
            with ui.tab_panel("keys"):
                _render_keys_tab()


def _logout():
    app.storage.user.clear()
    ui.navigate.to("/admin/login")


# ---------------------------------------------------------------- forms tab


@ui.refreshable
def _forms_list():
    with _session() as s:
        forms = forms_service.list_forms(s)
    if not forms:
        ui.label("No forms yet. Create your first one!").classes("text-gray-500")
        return
    for f in forms:
        with _session() as s:
            count = _response_count(s, f.id)
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.column().classes("gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f.title).classes("text-lg font-semibold")
                        ui.badge("active" if f.active else "closed", color="positive" if f.active else "grey")
                    if f.description:
                        ui.label(f.description).classes("text-sm text-gray-500")
                    ui.label(f"{count} response(s) · {_form_url(f.slug)}").classes("text-xs text-gray-400")
                with ui.row():
                    ui.button(icon="edit", on_click=lambda f=f: ui.navigate.to(f"/admin/forms/{f.id}")).props("flat").tooltip("Edit")
                    ui.button(icon="bar_chart", on_click=lambda f=f: ui.navigate.to(f"/admin/forms/{f.id}/responses")).props("flat").tooltip("Responses")
                    ui.button(icon="share", on_click=lambda f=f: _share_dialog(f)).props("flat").tooltip("Share link & code")
                    ui.button(icon="pause" if f.active else "play_arrow", on_click=lambda f=f: _toggle_form(f)).props("flat").tooltip("Close" if f.active else "Reopen")
                    ui.button(icon="delete", on_click=lambda f=f: _delete_dialog(f)).props("flat color=negative").tooltip("Delete")


def _render_forms_tab():
    def open_new_form_dialog():
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("New form").classes("text-lg font-semibold")
            title_in = ui.input("Title").classes("w-full")
            desc_in = ui.textarea("Description (optional)").classes("w-full")

            def create():
                try:
                    with _session() as s:
                        form = forms_service.create_form(s, title=title_in.value, description=desc_in.value)
                        form_id = form.id
                except ValueError as e:
                    ui.notify(str(e), type="negative")
                    return
                dialog.close()
                ui.navigate.to(f"/admin/forms/{form_id}")

            with ui.row():
                ui.button("Create", icon="add", on_click=create)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    with ui.row().classes("justify-between items-center w-full"):
        ui.label("Your forms").classes("text-lg font-semibold")
        ui.button("New form", icon="add", on_click=open_new_form_dialog)
    _forms_list()


def _form_url(slug: str) -> str:
    """Full public URL for a form, or a relative path if no base URL is configured."""
    if settings.base_url:
        return f"{settings.base_url}/f/{slug}"
    return f"/f/{slug}"


def _copy_to_clipboard(text: str) -> None:
    """Copy text in the browser, with a fallback for non-HTTPS (insecure) contexts.

    navigator.clipboard only exists on HTTPS or localhost; the classic
    textarea + execCommand trick still works everywhere else.
    """
    js_text = json.dumps(text)
    ui.run_javascript(
        """
        (function() {
            const text = %s;
            const fallback = () => {
                const ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).catch(fallback);
            } else {
                fallback();
            }
        })();
        """ % js_text
    )


def _copyable_field(label: str, value: str, *, help_text: str = "") -> None:
    """Render a readonly monospace field with a copy button and click feedback."""
    ui.label(label).classes("text-sm font-semibold mt-2")
    if help_text:
        ui.label(help_text).classes("text-xs text-gray-400")
    field = ui.input(value=value).props("readonly").classes("w-full") \
        .style("font-family: ui-monospace, monospace;")
    with field.add_slot("append"):
        def do_copy():
            _copy_to_clipboard(value)
            button.props("icon=check color=positive")
            def reset():
                button.props("icon=content_copy")
                button.remove_prop("color")
            ui.timer(1.5, reset, once=True)

        button = ui.button(icon="content_copy", on_click=do_copy) \
            .props("flat dense round size=sm").tooltip("Copy")


def _share_dialog(form):
    url = _form_url(form.slug)
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("Share this form").classes("text-lg font-semibold")
        ui.label("Send people this link and the access code:").classes("text-sm text-gray-500")
        _copyable_field("Link", url)
        _copyable_field(
            "WhatsApp link",
            f"<{url}>",
            help_text="Paste as-is in WhatsApp: it renders as a clickable link, without the link preview card.",
        )
        _copyable_field("Access code", form.access_code)
        ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def _toggle_form(form):
    with _session() as s:
        db_form = forms_service.get_form(s, form.id)
        forms_service.update_form(s, db_form, active=not db_form.active)
    _forms_list.refresh()


def _delete_dialog(form):
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Delete "{form.title}"?').classes("text-lg font-semibold")
        ui.label("All its responses will be deleted. This cannot be undone.").classes("text-sm text-gray-500")

        def do_delete():
            with _session() as s:
                db_form = forms_service.get_form(s, form.id)
                if db_form:
                    forms_service.delete_form(s, db_form)
            dialog.close()
            _forms_list.refresh()
            ui.notify("Form deleted", type="positive")

        with ui.row():
            ui.button("Delete", on_click=do_delete).props("color=negative")
            ui.button("Cancel", on_click=dialog.close).props("flat")
    dialog.open()


# ---------------------------------------------------------------- api keys tab


@ui.refreshable
def _keys_list():
    with _session() as s:
        keys = auth_service.list_api_keys(s)
    if not keys:
        ui.label("No API keys yet.").classes("text-gray-500")
        return
    for k in keys:
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.column().classes("gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(k.name).classes("font-semibold")
                        ui.badge("active" if k.active else "revoked", color="positive" if k.active else "grey")
                    last_used = (
                        k.last_used_at.strftime("%Y-%m-%d %H:%M") + " UTC" if k.last_used_at else "never used"
                    )
                    ui.label(f"created {k.created_at.strftime('%Y-%m-%d %H:%M')} · last used {last_used}").classes("text-xs text-gray-400")
                if k.active:
                    ui.button("Revoke", on_click=lambda k=k: _revoke_key(k)).props("outline color=negative")


def _render_keys_tab():
    def open_create_dialog():
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Create API key").classes("text-lg font-semibold")
            name_in = ui.input("Name (e.g. 'my-llm-agent')").classes("w-full")

            def create():
                with _session() as s:
                    _, plaintext = auth_service.create_api_key(s, name_in.value)
                dialog.close()
                _show_key_dialog(plaintext)

            with ui.row():
                ui.button("Create", on_click=create)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def _show_key_dialog(plaintext):
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("API key created").classes("text-lg font-semibold")
            ui.label("Copy it now — it will not be shown again:").classes("text-sm text-gray-500")
            ui.input("Key", value=plaintext).props("readonly").classes("w-full")
            ui.button("Done", on_click=dialog.close).props("flat")
        dialog.open()
        _keys_list.refresh()

    with ui.row().classes("justify-between items-center w-full"):
        ui.label("API keys").classes("text-lg font-semibold")
        ui.button("Create key", icon="add", on_click=open_create_dialog)
    ui.markdown(
        "Use these keys with the `X-API-Key` header to call the REST API at `/api/v1`. "
        "The OpenAPI schema is at `/api/v1/openapi.json` (also needs the key). "
        "See the README for examples."
    ).classes("text-sm text-gray-500")
    _keys_list()


def _revoke_key(key):
    with _session() as s:
        auth_service.revoke_api_key(s, key.id)
    _keys_list.refresh()


# ---------------------------------------------------------------- edit form page


@ui.page("/admin/forms/{form_id}", title="Edit form — Simple Forms")
def edit_form_page(form_id: int):
    if not _is_authenticated():
        ui.navigate.to("/admin/login")
        return
    with _session() as s:
        form = forms_service.get_form(s, form_id)
    if form is None:
        with ui.column().classes("max-w-xl mx-auto pt-24 items-center"):
            ui.label("Form not found.").classes("text-lg")
        return

    questions: list[dict] = [dict(q) for q in form.questions]

    with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/admin")).props("flat").tooltip("Back to forms")
            ui.label("Edit form").classes("text-2xl font-bold")

        with ui.card().classes("w-full"):
            title_in = ui.input("Title", value=form.title).classes("w-full")
            desc_in = ui.textarea("Description", value=form.description).classes("w-full")
            with ui.row().classes("items-end"):
                code_in = ui.input("Access code", value=form.access_code).classes("w-40")
                active_sw = ui.switch("Active (accepting responses)", value=form.active)

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Questions").classes("text-lg font-semibold")
                ui.button("Add question", icon="add", on_click=lambda: _add_question())

            @ui.refreshable
            def question_list():
                for idx, q in enumerate(questions):
                    _render_question_card(idx, q)

            def _add_question():
                questions.append({"type": "text", "label": "", "required": False})
                question_list.refresh()

            def _move(idx: int, delta: int):
                j = idx + delta
                if 0 <= j < len(questions):
                    questions[idx], questions[j] = questions[j], questions[idx]
                    question_list.refresh()

            def _remove(idx: int):
                questions.pop(idx)
                question_list.refresh()

            def _set(idx: int, key: str, value):
                questions[idx][key] = value

            def _set_type(idx: int, qtype: str):
                questions[idx]["type"] = qtype
                question_list.refresh()

            def _render_question_card(idx: int, q: dict):
                with ui.card().classes("w-full").props("flat bordered"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label(f"Q{idx + 1}").classes("font-bold")
                        with ui.row():
                            ui.button(icon="keyboard_arrow_up", on_click=lambda: _move(idx, -1)).props("flat dense")
                            ui.button(icon="keyboard_arrow_down", on_click=lambda: _move(idx, 1)).props("flat dense")
                            ui.button(icon="delete", on_click=lambda: _remove(idx)).props("flat dense color=negative")
                    ui.select(
                        QUESTION_TYPES, value=q["type"], label="Type",
                        on_change=lambda e, i=idx: _set_type(i, e.value),
                    ).classes("w-44")
                    ui.textarea(
                        "Label", value=q["label"],
                        on_change=lambda e, i=idx: _set(i, "label", e.value),
                    ).props("autogrow").classes("w-full")
                    ui.checkbox("Required", value=bool(q.get("required")), on_change=lambda e, i=idx: _set(i, "required", e.value))
                    if q["type"] in ("choice", "multi"):
                        ui.input(
                            "Options (comma separated)", value=", ".join(q.get("options", [])),
                            on_change=lambda e, i=idx: _set(
                                i, "options", [x.strip() for x in e.value.split(",") if x.strip()]
                            ),
                        ).classes("w-full")
                    if q["type"] == "scale":
                        with ui.row():
                            ui.number(
                                "Min", value=q.get("min", 1), min=-1000, max=1000,
                            ).on_value_change(lambda e, i=idx: _set(i, "min", int(e.value)))
                            ui.number(
                                "Max", value=q.get("max", 5), min=-1000, max=1000,
                            ).on_value_change(lambda e, i=idx: _set(i, "max", int(e.value)))
                    ui.input(
                        "Help text (optional)", value=q.get("help", ""),
                        on_change=lambda e, i=idx: _set(i, "help", e.value),
                    ).classes("w-full")

            question_list()

        with ui.row():
            ui.button("Save", icon="save", on_click=lambda: save()).props("color=primary")
            ui.button(
                "View responses", icon="bar_chart",
                on_click=lambda: ui.navigate.to(f"/admin/forms/{form.id}/responses"),
            ).props("outline")

    def save():
        payload = []
        for q in questions:
            item = dict(q)
            opts = item.get("options")
            if isinstance(opts, str):
                item["options"] = [x.strip() for x in opts.split(",") if x.strip()]
            payload.append(item)
        try:
            with _session() as s:
                db_form = forms_service.get_form(s, form.id)
                forms_service.update_form(
                    s, db_form,
                    title=title_in.value, description=desc_in.value,
                    access_code=code_in.value, active=active_sw.value,
                    questions=payload,
                )
                saved = [dict(q) for q in db_form.questions]
        except ValueError as e:
            ui.notify(str(e), type="negative")
            return
        questions[:] = saved
        question_list.refresh()
        ui.notify("Saved", type="positive")


# ---------------------------------------------------------------- responses page


@ui.page("/admin/forms/{form_id}/responses", title="Responses — Simple Forms")
def responses_page(form_id: int):
    if not _is_authenticated():
        ui.navigate.to("/admin/login")
        return
    with _session() as s:
        form = forms_service.get_form(s, form_id)
        responses = responses_service.list_responses(s, form_id) if form else []
    if form is None:
        with ui.column().classes("max-w-xl mx-auto pt-24 items-center"):
            ui.label("Form not found.").classes("text-lg")
        return

    def download_csv():
        csv_text = responses_service.responses_to_csv(form, responses)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_text)
            path = f.name
        ui.download(path, filename=f"{form.slug}-responses.csv")

    def view_response(r):
        with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full"):
            ui.label(f"Response #{r.id}").classes("text-lg font-semibold")
            ui.label(r.submitted_at.strftime("%Y-%m-%d %H:%M:%S UTC")).classes("text-xs text-gray-400")
            ui.separator()
            for q in form.questions:
                with ui.column().classes("w-full gap-0"):
                    ui.label(q["label"]).classes("text-sm font-semibold")
                    ui.label(responses_service.format_answer(r.answers.get(q["id"]))).classes("text-sm")
            ui.button("Close", on_click=dialog.close).props("flat")
        dialog.open()

    with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to(f"/admin/forms/{form.id}")).props("flat").tooltip("Back to form")
            ui.label("Responses").classes("text-2xl font-bold")
        with ui.row().classes("items-center justify-between w-full"):
            ui.label(f"{form.title} — {len(responses)} response(s)").classes("text-gray-500")
            ui.button("Download CSV", icon="download", on_click=download_csv).props("outline")

        if not responses:
            ui.label("No responses yet.").classes("text-gray-500")
            return
        for r in responses:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label(f"#{r.id} · {r.submitted_at.strftime('%Y-%m-%d %H:%M')} UTC").classes("text-sm text-gray-500")
                    ui.button("View answers", on_click=lambda r=r: view_response(r)).props("flat")
