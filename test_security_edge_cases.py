from __future__ import annotations

import json
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select


@pytest.fixture()
def client_and_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")

    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    db.engine = engine
    SQLModel.metadata.create_all(engine)

    with TestClient(app) as client:
        yield client, engine


def _create_user(engine, *, email: str, password: str, role: str, employee_id: str | None = None) -> None:
    from backend.models import User
    from backend.routers.auth import pwd_ctx

    with Session(engine) as session:
        session.add(
            User(
                email=email,
                hashed_password=pwd_ctx.hash(password),
                role=role,
                employee_id=employee_id,
            )
        )
        session.commit()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_and_owner_headers(client: TestClient) -> dict[str, str]:
    seed_resp = client.post("/seed")
    assert seed_resp.status_code == 200
    return _login(client, "owner@demo.com", "demo")


def _error_code(resp) -> str | None:
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("code")
    if isinstance(detail, str):
        return detail
    return None


def test_schedules_latest_requires_auth(client_and_engine):
    client, _ = client_and_engine
    resp = client.get("/schedules/latest")
    assert resp.status_code == 401
    assert _error_code(resp) == "unauthorized"


def test_schedules_latest_allows_authenticated_employee(client_and_engine):
    client, _ = client_and_engine
    _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")
    resp = client.get("/schedules/latest", headers=employee_headers)
    assert resp.status_code in {200, 404}


def test_seed_restricted_and_blocked_in_production(client_and_engine, monkeypatch):
    client, engine = client_and_engine

    monkeypatch.setenv("APP_ENV", "production")
    resp = client.post("/seed")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "seed_disabled_in_production"

    monkeypatch.setenv("APP_ENV", "staging")
    resp = client.post("/seed")
    assert resp.status_code == 401
    assert _error_code(resp) == "unauthorized"

    _create_user(engine, email="staging-owner@test.com", password="demo", role="owner")
    headers = _login(client, "staging-owner@test.com", "demo")
    resp = client.post("/seed", headers=headers)
    assert resp.status_code == 200


def test_legacy_pto_route_enforces_auth(client_and_engine):
    client, _ = client_and_engine
    target_date = (date.today() + timedelta(days=14)).isoformat()

    unauth = client.post(
        "/pto",
        json={"employee_id": "m1", "date": target_date, "kind": "pto", "hours": 8},
    )
    assert unauth.status_code == 401
    assert _error_code(unauth) == "unauthorized"

    headers = _seed_and_owner_headers(client)
    authed = client.post(
        "/pto",
        headers=headers,
        json={"employee_id": "m1", "date": target_date, "kind": "pto", "hours": 8},
    )
    assert authed.status_code == 200
    assert authed.json()["kind"] == "pto"


def test_legacy_pto_list_requires_auth_and_is_scoped_for_employee(client_and_engine):
    client, _ = client_and_engine
    unauth = client.get("/pto")
    assert unauth.status_code == 401
    assert _error_code(unauth) == "unauthorized"

    owner_headers = _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")
    target_date = (date.today() + timedelta(days=14)).isoformat()

    created_owner_pto = client.post(
        "/pto",
        headers=owner_headers,
        json={"employee_id": "m1", "date": target_date, "kind": "pto", "hours": 8},
    )
    assert created_owner_pto.status_code == 200

    created_employee_pto = client.post(
        "/pto",
        headers=employee_headers,
        json={"employee_id": "s1", "date": target_date, "kind": "pto", "hours": 0},
    )
    # s1 has no PTO; if submit is blocked, endpoint auth behavior is still validated above.
    assert created_employee_pto.status_code in {200, 400}
    if created_employee_pto.status_code == 400:
        assert _error_code(created_employee_pto) == "pto_hours_required"

    owner_list = client.get("/pto", headers=owner_headers)
    assert owner_list.status_code == 200
    assert isinstance(owner_list.json(), list)

    employee_list = client.get("/pto", headers=employee_headers)
    assert employee_list.status_code == 200
    for row in employee_list.json():
        assert row["employee_id"] == "s1"


def test_approve_past_dated_request_fails(client_and_engine):
    client, engine = client_and_engine
    headers = _seed_and_owner_headers(client)

    from backend.models import TimeOffRequest

    with Session(engine) as session:
        row = TimeOffRequest(
            employee_id="m1",
            date=date.today() - timedelta(days=1),
            kind="request_off",
            status="pending",
            hours=0.0,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        request_id = row.id

    resp = client.post(f"/time-off/requests/{request_id}/approve", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "cannot_approve_past_time_off_request"


def test_duplicate_time_off_submission_prevented(client_and_engine):
    client, _ = client_and_engine
    _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")
    target_date = (date.today() + timedelta(days=14)).isoformat()
    payload = {"employee_id": "s1", "date": target_date, "kind": "request_off", "hours": 0}

    first = client.post("/time-off/requests", headers=employee_headers, json=payload)
    assert first.status_code == 200

    second = client.post("/time-off/requests", headers=employee_headers, json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "duplicate_time_off_request_exists"


def test_duplicate_time_off_submission_prevented_when_already_approved(client_and_engine, monkeypatch):
    client, _ = client_and_engine
    monkeypatch.setenv("TIME_OFF_MIN_AVAILABLE_RATIO", "0")
    owner_headers = _seed_and_owner_headers(client)
    target_date = (date.today() + timedelta(days=14)).isoformat()

    created = client.post(
        "/time-off/requests",
        headers=owner_headers,
        json={"employee_id": "m1", "date": target_date, "kind": "pto", "hours": 8},
    )
    assert created.status_code == 200

    approved = client.post(
        f"/time-off/requests/{created.json()['id']}/approve",
        headers=owner_headers,
    )
    assert approved.status_code == 200

    duplicate_after_approved = client.post(
        "/time-off/requests",
        headers=owner_headers,
        json={"employee_id": "m1", "date": target_date, "kind": "pto", "hours": 8},
    )
    assert duplicate_after_approved.status_code == 409
    assert duplicate_after_approved.json()["detail"] == "duplicate_time_off_request_exists"


def test_pto_approval_never_goes_negative(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    d1 = (date.today() + timedelta(days=14)).isoformat()
    d2 = (date.today() + timedelta(days=15)).isoformat()

    r1 = client.post(
        "/time-off/requests",
        headers=owner_headers,
        json={"employee_id": "m1", "date": d1, "kind": "pto", "hours": 10},
    )
    r2 = client.post(
        "/time-off/requests",
        headers=owner_headers,
        json={"employee_id": "m1", "date": d2, "kind": "pto", "hours": 10},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    approve1 = client.post(f"/time-off/requests/{r1.json()['id']}/approve", headers=owner_headers)
    approve2 = client.post(f"/time-off/requests/{r2.json()['id']}/approve", headers=owner_headers)
    assert approve1.status_code == 200
    assert approve2.status_code == 400
    assert approve2.json()["detail"] == "cannot_approve_pto_insufficient_balance"

    employee = client.get("/employees/m1").json()
    assert employee["pto_balance_hours"] >= 0
    assert employee["pto_balance_hours"] == 6.0


def test_ai_regenerate_and_missing_reason_noop(client_and_engine, monkeypatch):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200
    schedule_run_id = generated.json()["schedule_run_id"]

    import backend.services.ai_service as ai_service
    from backend.models import ScheduleRun

    with Session(engine) as session:
        before_count = len(session.exec(select(ScheduleRun)).all())

    monkeypatch.setattr(
        ai_service,
        "_gemini_message",
        lambda user_message, context: ("Yes.\nREGENERATE: Rebalance hours fairly.", None),
    )
    regen = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "please rebalance", "context": {"schedule_run_id": schedule_run_id}},
    )
    assert regen.status_code == 200
    new_run_id = regen.json()["new_schedule_run_id"]
    assert new_run_id is not None
    assert new_run_id != schedule_run_id

    with Session(engine) as session:
        mid_count = len(session.exec(select(ScheduleRun)).all())
    assert mid_count == before_count + 1

    monkeypatch.setattr(ai_service, "_gemini_message", lambda user_message, context: ("Sure.\nREGENERATE:", None))
    noop = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "change it", "context": {"schedule_run_id": new_run_id}},
    )
    assert noop.status_code == 200
    assert noop.json()["new_schedule_run_id"] is None

    with Session(engine) as session:
        after_count = len(session.exec(select(ScheduleRun)).all())
    assert after_count == mid_count


def test_ai_chat_adjust_hours_asks_follow_up_when_underspecified(client_and_engine):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": (date.today() - timedelta(days=date.today().weekday())).isoformat()},
    )
    assert generated.status_code == 200

    from backend.models import ScheduleRun

    with Session(engine) as session:
        before_count = len(session.exec(select(ScheduleRun)).all())

    response = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "give Casey more hours"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_schedule_run_id"] is None
    assert "need a bit more detail" in body["assistant_message"].lower()
    assert "how many more or fewer hours" in body["assistant_message"].lower()

    with Session(engine) as session:
        after_count = len(session.exec(select(ScheduleRun)).all())
    assert after_count == before_count


def test_ai_chat_adjust_hours_creates_new_run_and_changes_hours(client_and_engine):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200
    initial_run_id = generated.json()["schedule_run_id"]
    initial_schedule = generated.json()["schedule"]
    initial_fairness_by_employee = {row["employee_id"]: row for row in initial_schedule["fairness_scores"]}
    before_s2_hours = float(initial_fairness_by_employee["s2"]["assigned_hours"])

    response = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": f"Give s2 8 more hours for current pay period starting {week_start}. Keep max 5 days."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_schedule_run_id"] is not None
    assert body["new_schedule_run_id"] != initial_run_id

    new_run = client.get(f"/schedules/{body['new_schedule_run_id']}", headers=owner_headers)
    assert new_run.status_code == 200
    new_schedule = new_run.json()["schedule"]
    new_fairness_by_employee = {row["employee_id"]: row for row in new_schedule["fairness_scores"]}
    after_s2_hours = float(new_fairness_by_employee["s2"]["assigned_hours"])
    assert after_s2_hours >= before_s2_hours
    assert new_schedule["fairness_scores"] != initial_schedule["fairness_scores"]


def test_ai_chat_fairness_target_followup_returns_token_without_redo(client_and_engine):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200

    from backend.models import ScheduleRun

    with Session(engine) as session:
        before_count = len(session.exec(select(ScheduleRun)).all())

    response = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "give Casey more hours so her fairness score goes up"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_schedule_run_id"] is None
    assert body.get("pending_intent_token")
    questions = body.get("follow_up_questions", [])
    assert len(questions) == 1
    assert "full utilization" in questions[0].lower()
    assert "pay period" not in questions[0].lower()
    assert "lowest-priority" not in questions[0].lower()

    with Session(engine) as session:
        after_count = len(session.exec(select(ScheduleRun)).all())
    assert after_count == before_count


def test_ai_chat_pending_fairness_intent_merges_answers_without_reasking_completed_fields(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200

    first = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "give more hours so fairness goes up"},
    )
    assert first.status_code == 200
    token = first.json().get("pending_intent_token")
    assert token

    second = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={
            "message": "Casey",
            "context": {"pending_intent_token": token},
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert body["new_schedule_run_id"] is None
    questions = body.get("follow_up_questions", [])
    assert len(questions) == 1
    assert "full utilization" in questions[0].lower()
    assert "which employee" not in questions[0].lower()
    assert body.get("pending_intent_token")


def test_ai_chat_fairness_target_answers_trigger_redo_and_metric_update(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200
    initial_run_id = generated.json()["schedule_run_id"]
    initial_fairness = {row["employee_id"]: row for row in generated.json()["schedule"]["fairness_scores"]}
    target_employee_id = min(
        initial_fairness.values(),
        key=lambda row: float(row["utilization"]),
    )["employee_id"]
    before_target_util = float(initial_fairness[target_employee_id]["utilization"])

    first = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": f"give {target_employee_id} more hours so their fairness score goes up"},
    )
    assert first.status_code == 200
    token = first.json().get("pending_intent_token")
    assert token

    second = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={
            "message": "full max hours",
            "context": {"pending_intent_token": token},
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert body["new_schedule_run_id"] is not None
    assert body["new_schedule_run_id"] != initial_run_id

    updated = client.get(f"/schedules/{body['new_schedule_run_id']}", headers=owner_headers)
    assert updated.status_code == 200
    updated_schedule = updated.json()["schedule"]
    updated_fairness = {row["employee_id"]: row for row in updated_schedule["fairness_scores"]}
    after_target_util = float(updated_fairness[target_employee_id]["utilization"])
    assert after_target_util >= before_target_util
    assert updated_schedule["overall_score"] is not None


def test_ai_chat_fairness_target_uses_defaults_and_executes_immediately(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200
    initial_run_id = generated.json()["schedule_run_id"]

    response = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={"message": "give Casey 100% fairness"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_schedule_run_id"] is not None
    assert body["new_schedule_run_id"] != initial_run_id
    assert not body.get("pending_intent_token")
    assert "full utilization" in body["assistant_message"].lower()
    assert "lowest-priority employees losing hours first" in body["assistant_message"].lower()


def test_ai_chat_strict_100_percent_infeasible_reports_reason(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200

    response = client.post(
        "/ai/chat",
        headers=owner_headers,
        json={
            "message": f"give m1 100% fairness for current pay period starting {week_start}. strict exact. lowest priority loses first. max 5 days/week.",
        },
    )
    assert response.status_code == 200
    assert response.json()["new_schedule_run_id"] is not None
    assert "INFEASIBLE" in response.json()["assistant_message"]
    assert "blocking constraint" in response.json()["assistant_message"].lower()

    run_resp = client.get(f"/schedules/{response.json()['new_schedule_run_id']}", headers=owner_headers)
    assert run_resp.status_code == 200
    schedule = run_resp.json()["schedule"]
    assert schedule["status"] == "infeasible"
    assert any(v.startswith("infeasible_utilization_target:") for v in schedule["violations"])
def test_redo_structured_flags_and_text_backcompat_exclude_owner(client_and_engine):
    client, engine = client_and_engine

    from backend.models import Availability, Employee, EmployeeJobRole, JobRole, Shift

    shift_date = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    _create_user(engine, email="owner@test.com", password="demo", role="owner", employee_id="e1")

    with Session(engine) as session:
        session.add(JobRole(name="cashier"))
        session.add(
            Employee(
                id="e1",
                name="Only Employee",
                max_weekly_hours=40,
                required_weekly_hours=40,
                role="regular",
                employment_type="full_time",
                category="server",
                pto_balance_hours=0,
            )
        )
        session.add(EmployeeJobRole(employee_id="e1", role_name="cashier"))
        for dow in range(7):
            session.add(
                Availability(
                    employee_id="e1",
                    day_of_week=dow,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                )
            )
        session.add(
            Shift(
                id="shift_1",
                date=shift_date,
                start_time=time(9, 0),
                end_time=time(17, 0),
                required_staff=2,
                required_category="server",
                required_role="cashier",
            )
        )
        session.commit()

    owner_headers = _login(client, "owner@test.com", "demo")

    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": shift_date.isoformat()},
    )
    assert generated.status_code == 200
    run_id = generated.json()["schedule_run_id"]
    assignments = generated.json()["schedule"]["assignments"]
    assert all(a["employee_id"] != "OWNER_ID" for a in assignments)
    assert any(v.startswith("infeasible_coverage_gap:") for v in generated.json()["schedule"]["violations"])

    # Backward compatibility: text reason still maps to exclude_owner behavior.
    redo_text = client.post(
        f"/schedules/{run_id}/redo",
        headers=owner_headers,
        json={"reason": "Do not put owner on schedule"},
    )
    assert redo_text.status_code == 200
    text_assignments = redo_text.json()["schedule"]["assignments"]
    assert all(a["employee_id"] != "OWNER_ID" for a in text_assignments)

    # Structured flag overrides textual parsing when explicitly false.
    redo_structured = client.post(
        f"/schedules/{redo_text.json()['schedule_run_id']}/redo",
        headers=owner_headers,
        json={"reason": "Do not put owner on schedule", "exclude_owner": False},
    )
    assert redo_structured.status_code == 200
    structured_assignments = redo_structured.json()["schedule"]["assignments"]
    assert any(a["employee_id"] == "OWNER_ID" for a in structured_assignments)
    assert all(
        a.get("override") is True and a.get("override_reason") == "OWNER_LAST_RESORT_INFEASIBLE"
        for a in structured_assignments
        if a["employee_id"] == "OWNER_ID"
    )

    # Baseline mode should honor the same service-layer conversion/override path.
    baseline_generated = client.post(
        "/schedules/generate?mode=baseline",
        headers=owner_headers,
        json={"week_start_date": shift_date.isoformat()},
    )
    assert baseline_generated.status_code == 200
    baseline_run_id = baseline_generated.json()["schedule_run_id"]

    baseline_redo_text = client.post(
        f"/schedules/{baseline_run_id}/redo",
        headers=owner_headers,
        json={"reason": "Do not put owner on schedule"},
    )
    assert baseline_redo_text.status_code == 200
    baseline_text_assignments = baseline_redo_text.json()["schedule"]["assignments"]
    assert all(a["employee_id"] != "OWNER_ID" for a in baseline_text_assignments)


def test_job_role_closure_auto_recomputes_when_edges_change(client_and_engine):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)

    assert client.post("/job-roles", headers=owner_headers, json={"name": "role_a"}).status_code == 200
    assert client.post("/job-roles", headers=owner_headers, json={"name": "role_b"}).status_code == 200
    assert client.post("/job-roles", headers=owner_headers, json={"name": "role_c"}).status_code == 200

    # Build transitive chain: role_c -> role_b -> role_a.
    e1 = client.post(
        "/job-roles/edges",
        headers=owner_headers,
        json={"from_role": "role_b", "to_role": "role_a"},
    )
    assert e1.status_code == 200
    e2 = client.post(
        "/job-roles/edges",
        headers=owner_headers,
        json={"from_role": "role_c", "to_role": "role_b"},
    )
    assert e2.status_code == 200

    from backend.models import JobRoleCoverClosure

    with Session(engine) as session:
        closure_row = session.get(JobRoleCoverClosure, "role_a")
        assert closure_row is not None
        covers = set(json.loads(closure_row.covers_json))

    # Auto-recompute should make role_a cover-set include the full transitive chain.
    assert {"role_a", "role_b", "role_c"}.issubset(covers)


def test_generate_schedule_includes_14_distinct_dates_when_14_day_shifts_exist(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()

    generated = client.post(
        "/schedules/generate?mode=optimized",
        headers=owner_headers,
        json={"week_start_date": week_start},
    )
    assert generated.status_code == 200
    run_id = generated.json()["schedule_run_id"]

    run = client.get(f"/schedules/{run_id}", headers=owner_headers)
    assert run.status_code == 200
    assignments = run.json()["schedule"]["assignments"]
    assigned_shift_ids = {a["shift_id"] for a in assignments}

    shifts_resp = client.get("/shifts", headers=owner_headers)
    assert shifts_resp.status_code == 200
    shift_date_by_id = {s["id"]: s["date"] for s in shifts_resp.json()}

    assigned_dates = {shift_date_by_id[sid] for sid in assigned_shift_ids if sid in shift_date_by_id}
    assert len(assigned_dates) == 14


def test_ai_health_reports_unavailable_and_available_states(client_and_engine, monkeypatch):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)

    import backend.routers.ai as ai_router

    monkeypatch.setattr(
        ai_router,
        "get_ai_health",
        lambda: (False, "gemini", "missing_api_key", "AI unavailable (missing API key)"),
    )
    down = client.get("/ai/health", headers=owner_headers)
    assert down.status_code == 200
    assert down.json()["ok"] is False
    assert down.json()["error_code"] == "missing_api_key"

    monkeypatch.setattr(
        ai_router,
        "get_ai_health",
        lambda: (True, "gemini", None, "AI provider reachable"),
    )
    up = client.get("/ai/health", headers=owner_headers)
    assert up.status_code == 200
    assert up.json()["ok"] is True
    assert up.json()["provider"] == "gemini"


def test_ai_chat_failure_returns_error_category(client_and_engine, monkeypatch):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)

    import backend.services.ai_service as ai_service

    monkeypatch.setattr(
        ai_service,
        "_gemini_message",
        lambda user_message, context: (
            "The AI assistant isn't available right now.",
            "timeout",
        ),
    )
    resp = client.post("/ai/chat", headers=owner_headers, json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.json()["error_code"] == "timeout"


def test_coverage_request_lifecycle_visible_to_employee(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")

    shifts = client.get("/shifts", headers=owner_headers)
    assert shifts.status_code == 200
    shift_id = shifts.json()[0]["id"]

    created = client.post(
        "/coverage-requests",
        headers=employee_headers,
        json={"requester_employee_id": "s1", "shift_id": shift_id, "reason": "Need coverage"},
    )
    assert created.status_code == 200
    request_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    pending = client.get("/coverage-requests/pending", headers=owner_headers)
    assert pending.status_code == 200
    assert any(row["id"] == request_id for row in pending.json())

    approved = client.patch(
        f"/coverage-requests/{request_id}/decision",
        headers=owner_headers,
        json={"decision": "approved", "cover_employee_id": "m1"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["cover_employee_id"] == "m1"

    mine = client.get("/coverage-requests/mine", headers=employee_headers)
    assert mine.status_code == 200
    matching = [row for row in mine.json() if row["id"] == request_id]
    assert matching
    assert matching[0]["status"] == "approved"


def test_coverage_owner_only_endpoints_block_employee(client_and_engine):
    client, _ = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")

    shifts = client.get("/shifts", headers=owner_headers)
    shift_id = shifts.json()[0]["id"]
    created = client.post(
        "/coverage-requests",
        headers=employee_headers,
        json={"requester_employee_id": "s1", "shift_id": shift_id},
    )
    assert created.status_code == 200
    request_id = created.json()["id"]

    blocked_pending = client.get("/coverage-requests/pending", headers=employee_headers)
    assert blocked_pending.status_code == 403
    assert _error_code(blocked_pending) == "forbidden"

    blocked_decision = client.patch(
        f"/coverage-requests/{request_id}/decision",
        headers=employee_headers,
        json={"decision": "denied"},
    )
    assert blocked_decision.status_code == 403
    assert _error_code(blocked_decision) == "forbidden"


def test_hours_request_lifecycle_upserts_preference_and_scheduler_uses_it(client_and_engine):
    client, engine = client_and_engine
    owner_headers = _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")

    period_start = date.today() - timedelta(days=date.today().weekday())
    period_end = period_start + timedelta(days=13)

    created = client.post(
        "/hours-requests",
        headers=employee_headers,
        json={
            "employee_id": "s1",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "requested_hours": 20,
            "note": "Need lighter pay period",
        },
    )
    assert created.status_code == 200
    request_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    pending = client.get("/hours-requests/pending", headers=owner_headers)
    assert pending.status_code == 200
    assert any(row["id"] == request_id for row in pending.json())

    approved = client.patch(
        f"/hours-requests/{request_id}/decision",
        headers=owner_headers,
        json={"decision": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    from backend.models import EmployeeHoursPreference
    from backend.services.scheduling_service import build_period_inputs

    with Session(engine) as session:
        pref = session.exec(
            select(EmployeeHoursPreference).where(
                EmployeeHoursPreference.employee_id == "s1",
                EmployeeHoursPreference.period_start == period_start,
                EmployeeHoursPreference.period_end == period_end,
            )
        ).first()
        assert pref is not None
        assert pref.requested_hours == 20

        employees, _, _, _ = build_period_inputs(session, period_start)
        employee = next(e for e in employees if e.id == "s1")
        assert employee.required_weekly_hours == 10


def test_hours_request_duplicate_pending_and_owner_only_controls(client_and_engine):
    client, _ = client_and_engine
    _seed_and_owner_headers(client)
    employee_headers = _login(client, "employee@demo.com", "demo")

    period_start = date.today() - timedelta(days=date.today().weekday())
    period_end = period_start + timedelta(days=13)
    payload = {
        "employee_id": "s1",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "requested_hours": 30,
    }

    first = client.post("/hours-requests", headers=employee_headers, json=payload)
    assert first.status_code == 200

    duplicate = client.post("/hours-requests", headers=employee_headers, json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "duplicate_pending_hours_request_exists"

    blocked_pending = client.get("/hours-requests/pending", headers=employee_headers)
    assert blocked_pending.status_code == 403
    assert _error_code(blocked_pending) == "forbidden"

    blocked_decision = client.patch(
        f"/hours-requests/{first.json()['id']}/decision",
        headers=employee_headers,
        json={"decision": "denied"},
    )
    assert blocked_decision.status_code == 403
    assert _error_code(blocked_decision) == "forbidden"
