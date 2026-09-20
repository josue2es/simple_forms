"""Public NiceGUI pages: landing page and form answering page."""

from nicegui import ui
from sqlmodel import Session

from ..db import engine
from ..service import forms as forms_service
from ..service import responses as responses_service


@ui.page("/", title="Simple Forms")
def index():
    with ui.column().classes("max-w-xl mx-auto pt-24 items-center text-center gap-2"):
        ui.label("Simple Forms").classes("text-3xl font-bold")
        ui.label("Create questionnaires and share them with a link and an access code.")
        ui.button("Admin panel", on_click=lambda: ui.navigate.to("/admin")).props("outline")


@ui.page("/f/{slug}", title="Questionnaire — Simple Forms")
def public_form(slug: str):
    with Session(engine) as session:
        form = forms_service.get_form_by_slug(session, slug)

    if form is None:
        with ui.column().classes("max-w-xl mx-auto pt-24 items-center text-center"):
            ui.icon("search_off", size="3em").classes("text-gray-400")
            ui.label("Form not found.").classes("text-lg")
        return

    state = {"stage": "code", "inputs": {}}  # stage: code | form | thanks

    def submit():
        answers = [
            {"question_id": qid, "value": el.value} for qid, el in state["inputs"].items()
        ]
        try:
            with Session(engine) as session:
                db_form = forms_service.get_form_by_slug(session, slug)
                responses_service.submit_response(session, db_form, answers)
        except ValueError as e:
            ui.notify(str(e), type="negative")
            return
        state["stage"] = "thanks"
        body.refresh()

    @ui.refreshable
    def body():
        with ui.column().classes("max-w-2xl mx-auto p-6 gap-4"):
            if state["stage"] == "code":
                _render_code_stage()
            elif state["stage"] == "form":
                _render_form_stage()
            else:
                _render_thanks()

    def _render_code_stage():
        if not form.active:
            ui.label("This form is closed.").classes("text-lg text-gray-500")
            return
        with ui.card().classes("w-full"):
            ui.label(form.title).classes("text-2xl font-bold")
            if form.description:
                ui.markdown(form.description).classes("text-gray-600")
            ui.separator()
            ui.label("Enter the access code you received to start.").classes("text-sm text-gray-500")
            code = ui.input("Access code").props("autofocus uppercase").classes("w-48")

            def check_code():
                if responses_service.check_access_code(form, code.value):
                    state["stage"] = "form"
                    body.refresh()
                else:
                    ui.notify("Wrong access code", type="negative")

            with ui.row():
                ui.button("Start", on_click=check_code)
            code.on("keydown.enter", check_code)

    def _render_question(q):
        qid = q["id"]
        required_mark = " *" if q.get("required") else ""
        ui.label(q["label"] + required_mark).classes("font-semibold")
        if q.get("help"):
            ui.label(q["help"]).classes("text-xs text-gray-500")
        qtype = q["type"]
        if qtype == "text":
            el = ui.input("Your answer").classes("w-full")
        elif qtype == "textarea":
            el = ui.textarea("Your answer").classes("w-full")
        elif qtype == "choice":
            el = ui.radio(q.get("options", []), value=None).classes("w-full")
        elif qtype == "multi":
            el = ui.option_group(q.get("options", []), value=[], type="checkbox").classes("w-full")
        else:  # scale
            el = ui.slider(min=q.get("min", 1), max=q.get("max", 5), value=q.get("min", 1))
            el.props("label-always snap").classes("w-full")
        state["inputs"][qid] = el

    def _render_form_stage():
        with ui.card().classes("w-full"):
            ui.label(form.title).classes("text-2xl font-bold")
            if form.description:
                ui.markdown(form.description).classes("text-gray-600")
            ui.separator()
            for q in form.questions:
                with ui.column().classes("w-full gap-1"):
                    _render_question(q)
            ui.separator()
            ui.button("Submit", icon="send", on_click=submit).props("color=primary")

    def _render_thanks():
        with ui.card().classes("w-full items-center py-12"):
            ui.icon("check_circle", size="4em", color="positive")
            ui.label("Thank you!").classes("text-2xl font-bold")
            ui.label("Your response has been recorded.").classes("text-gray-500")

    body()
