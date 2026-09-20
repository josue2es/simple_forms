import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.ratelimit import limiter


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


AUTH = {"X-API-Key": settings.master_api_key}


def create_sample_form(client):
    payload = {
        "title": "Customer Feedback",
        "description": "Tell us what you think",
        "questions": [
            {"type": "text", "label": "Your name", "required": True},
            {"type": "choice", "label": "How did you hear about us?", "options": ["web", "friend", "other"]},
            {"type": "multi", "label": "What did you like?", "options": ["price", "quality", "support"]},
            {"type": "scale", "label": "Overall satisfaction", "min": 1, "max": 5, "required": True},
        ],
    }
    r = client.post("/api/v1/forms", json=payload, headers=AUTH)
    assert r.status_code == 201, r.text
    return r.json()


def test_api_key_required(client):
    # Invalid keys return 404 (not 401/403) so management routes aren't enumerable.
    r = client.get("/api/v1/forms")
    assert r.status_code == 404
    r = client.get("/api/v1/forms", headers={"X-API-Key": "wrong"})
    assert r.status_code == 404


def test_openapi_schema_behind_api_key(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 404
    r = client.get("/api/v1/openapi.json", headers={"X-API-Key": "wrong"})
    assert r.status_code == 404
    r = client.get("/api/v1/openapi.json", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["paths"]["/api/v1/forms/{slug}/responses"]


def test_builtin_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_form_lifecycle(client):
    form = create_sample_form(client)
    assert form["slug"] and form["access_code"]
    assert len(form["questions"]) == 4
    q_ids = [q["id"] for q in form["questions"]]
    assert len(set(q_ids)) == 4

    # list & get
    assert any(f["id"] == form["id"] for f in client.get("/api/v1/forms", headers=AUTH).json())
    got = client.get(f"/api/v1/forms/{form['id']}", headers=AUTH).json()
    assert got["title"] == "Customer Feedback"

    # update
    r = client.patch(f"/api/v1/forms/{form['id']}", json={"title": "Feedback v2"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["title"] == "Feedback v2"

    # delete
    r = client.delete(f"/api/v1/forms/{form['id']}", headers=AUTH)
    assert r.status_code == 204
    assert client.get(f"/api/v1/forms/{form['id']}", headers=AUTH).status_code == 404


def test_submission_and_retrieval(client):
    form = create_sample_form(client)
    q_ids = {q["label"]: q["id"] for q in form["questions"]}
    submit = f"/api/v1/forms/{form['slug']}/responses"

    # wrong access code
    r = client.post(
        submit,
        json={"access_code": "WRONG", "answers": []},
    )
    assert r.status_code == 403

    # missing required answers
    r = client.post(
        submit,
        json={"access_code": form["access_code"], "answers": []},
    )
    assert r.status_code == 400

    # invalid choice option
    r = client.post(
        submit,
        json={
            "access_code": form["access_code"],
            "answers": [
                {"question_id": q_ids["Your name"], "value": "Alice"},
                {"question_id": q_ids["Overall satisfaction"], "value": 4},
                {"question_id": q_ids["How did you hear about us?"], "value": "tv"},
            ],
        },
    )
    assert r.status_code == 400 and "not a valid option" in r.text

    # valid submission (case-insensitive code)
    r = client.post(
        submit,
        json={
            "access_code": form["access_code"].lower(),
            "answers": [
                {"question_id": q_ids["Your name"], "value": "Alice"},
                {"question_id": q_ids["How did you hear about us?"], "value": "web"},
                {"question_id": q_ids["What did you like?"], "value": ["price", "quality"]},
                {"question_id": q_ids["Overall satisfaction"], "value": 5},
            ],
        },
    )
    assert r.status_code == 201, r.text

    # retrieve responses
    responses = client.get(f"/api/v1/forms/{form['id']}/responses", headers=AUTH).json()
    assert len(responses) == 1
    assert responses[0]["answers"][q_ids["Your name"]] == "Alice"

    # CSV export
    r = client.get(f"/api/v1/forms/{form['id']}/responses.csv", headers=AUTH)
    assert r.status_code == 200 and "Alice" in r.text

    # summary
    summary = client.get(f"/api/v1/forms/{form['id']}/summary", headers=AUTH).json()
    assert summary["total_responses"] == 1
    by_id = {q["question_id"]: q for q in summary["questions"]}
    assert by_id[q_ids["What did you like?"]]["counts"] == {"price": 1, "quality": 1}
    assert by_id[q_ids["Overall satisfaction"]]["counts"] == {"5": 1}


def test_closed_form_rejects_submissions(client):
    form = create_sample_form(client)
    client.patch(f"/api/v1/forms/{form['id']}", json={"active": False}, headers=AUTH)
    q_id = form["questions"][0]["id"]
    r = client.post(
        f"/api/v1/forms/{form['slug']}/responses",
        json={"access_code": form["access_code"], "answers": [{"question_id": q_id, "value": "x"}]},
    )
    assert r.status_code == 400 and "closed" in r.text


def test_generated_access_code_is_long(client):
    form = create_sample_form(client)
    assert len(form["access_code"]) >= 10


def test_submission_rate_limited(client):
    limiter.reset()  # isolate from submissions made by other tests (same test IP)
    form = create_sample_form(client)
    submit = f"/api/v1/forms/{form['slug']}/responses"
    codes = []
    for _ in range(11):
        r = client.post(submit, json={"access_code": "WRONG", "answers": []})
        codes.append(r.status_code)
    assert codes[:10] == [403] * 10  # within the limit: processed (and rejected)
    assert codes[10] == 429  # over the limit: rate limited
    limiter.reset()


def test_question_validation(client):
    r = client.post(
        "/api/v1/forms",
        json={"title": "Bad form", "questions": [{"type": "choice", "label": "Pick", "options": []}]},
        headers=AUTH,
    )
    assert r.status_code == 400 and "option" in r.text
