from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, delete, select


def _monday() -> str:
    week_start = date.today() - timedelta(days=date.today().weekday())
    return week_start.isoformat()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_and_owner_headers(client: TestClient) -> dict[str, str]:
    seeded = client.post("/seed")
    assert seeded.status_code == 200
    return _login(client, "owner@demo.com", "demo")


def _to_minutes(value: str) -> int:
    hour, minute, *_ = value.split(":")
    return int(hour) * 60 + int(minute)


def test_seeded_schedule_excludes_owner_and_covers_store_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)

        employees = client.get("/employees", headers=owner_headers)
        assert employees.status_code == 200
        employee_rows = employees.json()
        assert len(employee_rows) == 16
        assert all(e["active"] is True for e in employee_rows)
        assert sum(1 for e in employee_rows if e["category"] == "cook") == 4
        assert sum(1 for e in employee_rows if e["category"] == "server") == 4
        assert sum(1 for e in employee_rows if e["category"] == "busser") == 4
        assert sum(1 for e in employee_rows if e["role"] == "manager") == 2
        assert sum(1 for e in employee_rows if e["role"] == "shift_lead") == 2

        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        assert schedule["status"] == "success"
        assignments = schedule["assignments"]
        assert all(a["employee_id"] != "OWNER_ID" for a in assignments)

        shifts = client.get("/shifts", headers=owner_headers)
        assert shifts.status_code == 200
        shift_by_id = {s["id"]: s for s in shifts.json()}

        availability = client.get("/availability", headers=owner_headers)
        assert availability.status_code == 200
        slots_by_employee_day: dict[tuple[str, int], list[tuple[int, int]]] = {}
        for slot in availability.json():
            key = (slot["employee_id"], slot["day_of_week"])
            slots_by_employee_day.setdefault(key, []).append(
                (_to_minutes(slot["start_time"]), _to_minutes(slot["end_time"]))
            )

        for assignment in assignments:
            shift = shift_by_id[assignment["shift_id"]]
            employee_id = assignment["employee_id"]
            day_of_week = date.fromisoformat(shift["date"]).weekday()
            slots = slots_by_employee_day.get((employee_id, day_of_week), [])
            start_min = _to_minutes(shift["start_time"])
            end_min = _to_minutes(shift["end_time"])
            assert any(start_min >= s and end_min <= e for s, e in slots)

        categories = {s["required_category"] for s in shift_by_id.values() if s.get("required_category")}
        intervals_by_day_category: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for assignment in assignments:
            shift = shift_by_id[assignment["shift_id"]]
            key = (shift["date"], shift["required_category"])
            intervals_by_day_category.setdefault(key, []).append(
                (_to_minutes(shift["start_time"]), _to_minutes(shift["end_time"]))
            )

        all_dates = sorted({s["date"] for s in shift_by_id.values()})
        assert len(all_dates) == 14
        starts_by_day = {}
        for shift in shift_by_id.values():
            starts_by_day.setdefault(shift["date"], set()).add(_to_minutes(shift["start_time"]))
        assert len({start for starts in starts_by_day.values() for start in starts}) > 2
        for day in all_dates:
            for category in categories:
                intervals = intervals_by_day_category.get((day, category), [])
                for hour in range(9, 23):
                    probe = hour * 60 + 30
                    assert any(start <= probe < end for start, end in intervals)

        employee_type_by_id = {e["id"]: e["employment_type"] for e in employee_rows}
        part_time_assignments = 0
        for assignment in assignments:
            shift = shift_by_id[assignment["shift_id"]]
            if employee_type_by_id.get(assignment["employee_id"]) != "part_time":
                continue
            part_time_assignments += 1
        assert part_time_assignments > 0


def test_owner_override_only_when_explicitly_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Availability

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        with Session(db.engine) as session:
            session.exec(delete(Availability).where(Availability.employee_id != "m1"))
            session.commit()

        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        assert all(a["employee_id"] != "OWNER_ID" for a in schedule["assignments"])
        assert any(v.startswith("infeasible_coverage_gap:") for v in schedule["violations"])

        redo = client.post(
            f"/schedules/{generated.json()['schedule_run_id']}/redo",
            headers=owner_headers,
            json={"reason": "Allow owner override for infeasible schedule", "exclude_owner": False},
        )
        assert redo.status_code == 200
        owner_assignments = [a for a in redo.json()["schedule"]["assignments"] if a["employee_id"] == "OWNER_ID"]
        assert owner_assignments
        assert all(a.get("override") is True for a in owner_assignments)
        assert all(a.get("override_reason") == "OWNER_LAST_RESORT_INFEASIBLE" for a in owner_assignments)


def test_inactive_employees_are_excluded_from_api_and_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Employee

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)

        with Session(db.engine) as session:
            employee = session.get(Employee, "s4")
            assert employee is not None
            employee.active = False
            session.add(employee)
            session.commit()

        employees = client.get("/employees", headers=owner_headers)
        assert employees.status_code == 200
        employee_ids = {row["id"] for row in employees.json()}
        assert len(employee_ids) == 15
        assert "s4" not in employee_ids

        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        assignments = generated.json()["schedule"]["assignments"]
        assert all(a["employee_id"] != "s4" for a in assignments)


def test_fairness_metrics_recompute_when_assignments_change(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Availability, Employee

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        first = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert first.status_code == 200
        first_schedule = first.json()["schedule"]
        first_run_id = first.json()["schedule_run_id"]
        first_overall = first_schedule["overall_score"]
        first_s1 = next(row for row in first_schedule["fairness_scores"] if row["employee_id"] == "s1")

        with Session(db.engine) as session:
            s1 = session.exec(select(Employee).where(Employee.id == "s1")).first()
            assert s1 is not None
            s1.required_weekly_hours = max(1.0, s1.required_weekly_hours - 10.0)
            session.add(s1)
            session.exec(delete(Availability).where(Availability.employee_id == "s1", Availability.day_of_week == 0))
            session.commit()

        second = client.post(
            f"/schedules/{first_run_id}/redo",
            headers=owner_headers,
            json={"reason": "Rebalance after updated availability and requested hours"},
        )
        assert second.status_code == 200
        second_schedule = second.json()["schedule"]
        second_overall = second_schedule["overall_score"]
        second_s1 = next(row for row in second_schedule["fairness_scores"] if row["employee_id"] == "s1")

        assert first_s1["assigned_hours"] != second_s1["assigned_hours"] or first_s1["utilization"] != second_s1["utilization"]
        assert first_schedule["fairness_scores"] != second_schedule["fairness_scores"]
        assert round(sum(row["percentage"] for row in first_schedule["fairness_scores"]) / len(first_schedule["fairness_scores"]), 4) == round(first_overall, 4)
        assert round(sum(row["percentage"] for row in second_schedule["fairness_scores"]) / len(second_schedule["fairness_scores"]), 4) == round(second_overall, 4)
        assert "max_hours" in first_s1
        assert "utilization" in first_s1


def test_generate_upgrades_rigid_two_block_shift_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Shift

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        period_start = date.fromisoformat(_monday())
        period_end = period_start + timedelta(days=13)

        # Force legacy rigid shape: only 9-16 and 16-23 for all period shifts.
        with Session(db.engine) as session:
            period_shifts = session.exec(
                select(Shift).where(Shift.date >= period_start, Shift.date <= period_end)
            ).all()
            for idx, row in enumerate(period_shifts):
                if idx % 2 == 0:
                    row.start_time = time(9, 0)
                    row.end_time = time(16, 0)
                else:
                    row.start_time = time(16, 0)
                    row.end_time = time(23, 0)
                session.add(row)
            session.commit()

        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": period_start.isoformat()},
        )
        assert generated.status_code == 200

        shifts_resp = client.get("/shifts", headers=owner_headers)
        assert shifts_resp.status_code == 200
        period_shifts = [
            row for row in shifts_resp.json() if period_start.isoformat() <= row["date"] <= period_end.isoformat()
        ]
        unique_pairs = {(row["start_time"], row["end_time"]) for row in period_shifts}
        assert len(unique_pairs) > 2


def test_non_owner_assignments_respect_max_5_days_per_week_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        shifts = client.get("/shifts", headers=owner_headers).json()
        shift_date_by_id = {row["id"]: date.fromisoformat(row["date"]) for row in shifts}

        days_by_employee_week: dict[tuple[str, str], set[str]] = {}
        for assignment in schedule["assignments"]:
            employee_id = assignment["employee_id"]
            if employee_id == "OWNER_ID":
                continue
            if assignment.get("override") and assignment.get("override_reason") == "COVERAGE_OVERRIDE_MAX_DAYS":
                continue
            shift_date = shift_date_by_id[assignment["shift_id"]]
            week_start = (shift_date - timedelta(days=shift_date.weekday())).isoformat()
            key = (employee_id, week_start)
            days_by_employee_week.setdefault(key, set()).add(shift_date.isoformat())

        assert all(len(days) <= 5 for days in days_by_employee_week.values())


def test_approved_coverage_request_allows_day6_with_override(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Availability, CoverageRequest, Employee, Shift

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        week_start = date.fromisoformat(_monday())

        with Session(db.engine) as session:
            session.exec(delete(Availability))
            session.exec(delete(Shift))
            employee = session.get(Employee, "s1")
            assert employee is not None
            employee.max_weekly_hours = 80
            employee.required_weekly_hours = 40
            session.add(employee)
            for dow in range(6):
                session.add(
                    Availability(
                        employee_id="s1",
                        day_of_week=dow,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                    )
                )
                shift_date = week_start + timedelta(days=dow)
                session.add(
                    Shift(
                        id=f"max_days_shift_{dow}",
                        date=shift_date,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                        required_staff=1,
                        required_category="server",
                        required_role="cashier",
                    )
                )
            session.commit()

        first = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": week_start.isoformat()},
        )
        assert first.status_code == 200
        assert any("max_days_per_week" in v for v in first.json()["schedule"]["violations"])
        assert any(v.startswith("infeasible_coverage_gap:") for v in first.json()["schedule"]["violations"])
        assert not any(
            row["shift_id"] == "max_days_shift_5" and row["employee_id"] == "s1"
            for row in first.json()["schedule"]["assignments"]
        )

        with Session(db.engine) as session:
            session.add(
                CoverageRequest(
                    requester_employee_id="s2",
                    shift_id="max_days_shift_5",
                    status="approved",
                    cover_employee_id="s1",
                    reason="Coverage needed",
                )
            )
            session.commit()

        second = client.post(
            f"/schedules/{first.json()['schedule_run_id']}/redo",
            headers=owner_headers,
            json={"reason": "Apply approved coverage"},
        )
        assert second.status_code == 200
        matching = [
            row
            for row in second.json()["schedule"]["assignments"]
            if row["shift_id"] == "max_days_shift_5" and row["employee_id"] == "s1"
        ]
        assert matching
        assert matching[0].get("override") is True
        assert matching[0].get("override_reason") == "COVERAGE_OVERRIDE_MAX_DAYS"


def test_priority_ranking_prefers_manager_when_candidates_are_equally_feasible():
    from backend.scheduler import generate_greedy_schedule
    from backend.schemas import Availability, Employee, EmploymentType, Role, Shift

    shift_date = date.today() - timedelta(days=date.today().weekday())
    employees = [
        Employee(
            id="mgr",
            name="Manager Candidate",
            max_weekly_hours=40,
            required_weekly_hours=20,
            role=Role.MANAGER,
            employment_type=EmploymentType.FULL_TIME,
            category="server",
            job_roles=["cashier"],
        ),
        Employee(
            id="reg",
            name="Regular Candidate",
            max_weekly_hours=40,
            required_weekly_hours=20,
            role=Role.REGULAR,
            employment_type=EmploymentType.FULL_TIME,
            category="server",
            job_roles=["cashier"],
        ),
    ]
    availability = [
        Availability(employee_id="mgr", day_of_week=shift_date.weekday(), start_time=time(9, 0), end_time=time(17, 0)),
        Availability(employee_id="reg", day_of_week=shift_date.weekday(), start_time=time(9, 0), end_time=time(17, 0)),
    ]
    shifts = [
        Shift(
            id="priority_shift",
            date=shift_date,
            start_time=time(9, 0),
            end_time=time(15, 0),
            required_role="cashier",
            required_staff=1,
            required_category="server",
        )
    ]

    assignments = generate_greedy_schedule(
        employees=employees,
        availability=availability,
        pto=[],
        shifts=shifts,
        role_cover_map={"cashier": {"cashier"}},
        exclude_owner=True,
    )

    assert assignments
    assert assignments[0].employee_id == "mgr"


def test_seeded_shifts_have_diverse_start_times_including_mid_and_pt(tmp_path, monkeypatch):
    """Seed must produce >4 unique shift start times including at least one mid and one short PT."""
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        shifts = client.get("/shifts", headers=owner_headers)
        assert shifts.status_code == 200
        rows = shifts.json()

        unique_starts = {row["start_time"][:5] for row in rows}
        unique_pairs = {(row["start_time"][:5], row["end_time"][:5]) for row in rows}

        # Must have >4 distinct start times across the 14-day period.
        assert len(unique_starts) > 4, f"Only {len(unique_starts)} unique starts: {sorted(unique_starts)}"

        # Must include at least one mid shift (opener after 10:00).
        mid_starts = {s for s in unique_starts if "11:" <= s <= "13:59"}
        assert mid_starts, f"No mid shifts found; starts: {sorted(unique_starts)}"

        # Must include at least one short PT shift (≤5h, starts at 16:00 or later).
        short_pt = {p for p in unique_pairs if p[0] >= "16:" and
                    (_to_minutes(p[1]) - _to_minutes(p[0])) <= 5 * 60}
        assert short_pt, f"No short PT shift found; pairs: {sorted(unique_pairs)}"


def test_narrow_availability_employee_assigned_to_matching_short_shift():
    """Employee available only 16:00–21:00 must be assigned to a 16–21 shift, not a longer one."""
    from backend.scheduler import generate_greedy_schedule
    from backend.schemas import Availability, Employee, EmploymentType, Role, Shift

    shift_date = date.today() - timedelta(days=date.today().weekday())  # Monday
    employees = [
        Employee(
            id="ft",
            name="FT Employee",
            max_weekly_hours=40,
            required_weekly_hours=20,
            role=Role.REGULAR,
            employment_type=EmploymentType.FULL_TIME,
            category="cook",
            job_roles=["prep_cook"],
        ),
        Employee(
            id="pt_narrow",
            name="PT Narrow",
            max_weekly_hours=20,
            required_weekly_hours=10,
            role=Role.REGULAR,
            employment_type=EmploymentType.PART_TIME,
            category="cook",
            job_roles=["prep_cook"],
        ),
    ]
    availability = [
        # FT employee available all day
        Availability(employee_id="ft", day_of_week=shift_date.weekday(),
                     start_time=time(9, 0), end_time=time(23, 0)),
        # PT employee only available 16:00–21:00
        Availability(employee_id="pt_narrow", day_of_week=shift_date.weekday(),
                     start_time=time(16, 0), end_time=time(21, 0)),
    ]
    shifts = [
        Shift(id="long_shift", date=shift_date,
              start_time=time(9, 0), end_time=time(15, 0),
              required_staff=1, required_category="cook", required_role="prep_cook"),
        Shift(id="pt_shift", date=shift_date,
              start_time=time(16, 0), end_time=time(21, 0),
              required_staff=1, required_category="cook", required_role="prep_cook"),
    ]

    assignments = generate_greedy_schedule(
        employees=employees,
        availability=availability,
        pto=[],
        shifts=shifts,
        role_cover_map={"prep_cook": {"prep_cook"}},
        exclude_owner=True,
    )

    assigned = {a.shift_id: a.employee_id for a in assignments}
    # FT must do the long shift; PT narrow must do the PT slot.
    assert assigned.get("long_shift") == "ft"
    assert assigned.get("pt_shift") == "pt_narrow"


def test_generated_schedule_includes_mid_and_pt_shifts(tmp_path, monkeypatch):
    """Generated period shifts must include at least one mid and one short PT template."""
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        gen = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert gen.status_code == 200
        assert gen.json()["schedule"]["status"] == "success"

        shift_resp = client.get("/shifts", headers=owner_headers)
        shift_by_id = {s["id"]: s for s in shift_resp.json()}

        period_pairs = {
            (row["start_time"][:5], row["end_time"][:5])
            for row in shift_by_id.values()
        }

        # At least one mid shift template (11-19 / 12-20 / 13-21 / 14-19).
        mid_templates = {("11:00", "19:00"), ("12:00", "20:00"), ("13:00", "21:00"), ("14:00", "19:00")}
        assert period_pairs.intersection(mid_templates), f"No mid shift template found; pairs={sorted(period_pairs)}"

        # At least one short PT shift template (4-9 / 4-8 / 5-9 / 6-11).
        short_templates = {("16:00", "21:00"), ("16:00", "20:00"), ("17:00", "21:00"), ("18:00", "23:00")}
        assert period_pairs.intersection(short_templates), f"No short PT template found; pairs={sorted(period_pairs)}"


def test_schedule_grid_keeps_distinct_time_blocks_instead_of_time_buckets():
    source = Path("frontend/src/components/ScheduleGrid.tsx").read_text(encoding="utf-8")
    assert "for (const shift of dayShifts)" in source
    assert "startTime: shift.start_time" in source
    assert "endTime: shift.end_time" in source
    assert "{formatEtTime(card.startTime)} - {formatEtTime(card.endTime)}" in source


def test_full_time_shift_leads_meet_min_utilization_or_report_violation(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        fairness = {row["employee_id"]: row for row in schedule["fairness_scores"]}
        shift_lead_ids = {"l1", "l2"}
        lead_floor = 0.70
        unmet = []
        for lead_id in shift_lead_ids:
            lead = fairness.get(lead_id)
            assert lead is not None
            max_hours = float(lead.get("max_hours") or 0.0)
            assigned = float(lead.get("assigned_hours") or 0.0)
            if max_hours > 0 and assigned + 0.01 < max_hours * lead_floor:
                unmet.append(lead_id)
        if unmet:
            assert any(v.startswith("LEADERSHIP_MIN_HOURS_NOT_MET:") for v in schedule["violations"])


def test_fairness_uses_max_hours_not_requested_hours():
    from backend.fairness import calculate_fairness
    from backend.schemas import Assignment, Employee, EmploymentType, Role, Shift

    shift_date = date.today() - timedelta(days=date.today().weekday())
    shifts = [
        Shift(
            id="shift_a",
            date=shift_date,
            start_time=time(9, 0),
            end_time=time(17, 0),
            required_staff=1,
            required_category="server",
            required_role="cashier",
        )
    ]
    assignments = [Assignment(shift_id="shift_a", employee_id="emp")]
    employee_low_requested = Employee(
        id="emp",
        name="Employee",
        max_weekly_hours=40,
        required_weekly_hours=8,
        role=Role.REGULAR,
        employment_type=EmploymentType.FULL_TIME,
        category="server",
        job_roles=["cashier"],
    )
    employee_high_requested = employee_low_requested.model_copy(update={"required_weekly_hours": 40})

    low_scores = calculate_fairness([employee_low_requested], shifts, assignments, weeks_in_period=1.0)
    high_scores = calculate_fairness([employee_high_requested], shifts, assignments, weeks_in_period=1.0)
    assert low_scores[0].utilization == high_scores[0].utilization
    assert low_scores[0].percentage == high_scores[0].percentage


def test_shift_lead_only_leadership_is_infeasible_without_manager_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app
    from backend.models import Availability

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        with Session(db.engine) as session:
            session.exec(delete(Availability).where(Availability.employee_id.in_(["m1", "m2"])))
            session.commit()

        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        assert schedule["status"] == "infeasible"
        assert any(v.startswith("MISSING_MANAGER_COVERAGE:") for v in schedule["violations"])


def test_feasible_seed_has_manager_coverage_and_shift_lead_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        assignments = schedule["assignments"]

        employees = client.get("/employees", headers=owner_headers).json()
        role_by_employee = {row["id"]: row["role"] for row in employees}
        shifts = client.get("/shifts", headers=owner_headers).json()

        manager_shift_ids = [row["id"] for row in shifts if "_mgr_" in row["id"] and row["required_category"] == "leadership"]
        assert manager_shift_ids
        for shift_id in manager_shift_ids:
            assigned = [a for a in assignments if a["shift_id"] == shift_id]
            assert assigned, f"missing assignment for manager shift {shift_id}"
            assert all(role_by_employee.get(a["employee_id"]) == "manager" for a in assigned)

        shift_lead_assignments = [
            a for a in assignments if role_by_employee.get(a["employee_id"]) == "shift_lead"
        ]
        assert shift_lead_assignments, "shift leads should still receive hours"

        # Shift lead support slots can be filled by managers when needed.
        support_shift_ids = [row["id"] for row in shifts if "_lead_support_" in row["id"]]
        assert support_shift_ids
        support_assigned_roles = {
            role_by_employee.get(a["employee_id"])
            for a in assignments
            if a["shift_id"] in support_shift_ids
        }
        assert support_assigned_roles.issubset({"manager", "shift_lead"})


def test_shift_lead_never_satisfies_manager_required_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    from backend import db
    from backend.main import app

    test_db = tmp_path / "test.db"
    db.engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(db.engine)

    with TestClient(app) as client:
        owner_headers = _seed_and_owner_headers(client)
        generated = client.post(
            "/schedules/generate?mode=optimized",
            headers=owner_headers,
            json={"week_start_date": _monday()},
        )
        assert generated.status_code == 200
        schedule = generated.json()["schedule"]
        assignments = schedule["assignments"]

        employees = client.get("/employees", headers=owner_headers).json()
        role_by_employee = {row["id"]: row["role"] for row in employees}

        for assignment in assignments:
            if "_mgr_" not in assignment["shift_id"]:
                continue
            assert role_by_employee.get(assignment["employee_id"]) == "manager"


def test_manager_can_fill_shift_lead_support_slot_when_needed():
    from backend.scheduler import generate_greedy_schedule
    from backend.schemas import Availability, Employee, EmploymentType, Role, Shift

    shift_date = date.today() - timedelta(days=date.today().weekday())
    employees = [
        Employee(
            id="mgr",
            name="Manager",
            max_weekly_hours=56,
            required_weekly_hours=40,
            role=Role.MANAGER,
            employment_type=EmploymentType.FULL_TIME,
            category="leadership",
            job_roles=["server_lead"],
        ),
        Employee(
            id="lead",
            name="Shift Lead",
            max_weekly_hours=40,
            required_weekly_hours=30,
            role=Role.SHIFT_LEAD,
            employment_type=EmploymentType.FULL_TIME,
            category="leadership",
            job_roles=["server_lead"],
        ),
    ]
    availability = [
        Availability(employee_id="mgr", day_of_week=shift_date.weekday(), start_time=time(16, 0), end_time=time(21, 0)),
        # Shift lead unavailable for this support window.
        Availability(employee_id="lead", day_of_week=shift_date.weekday(), start_time=time(9, 0), end_time=time(15, 0)),
    ]
    shifts = [
        Shift(
            id=f"ld_lead_support_{shift_date.isoformat()}",
            date=shift_date,
            start_time=time(16, 0),
            end_time=time(21, 0),
            required_staff=1,
            required_category="leadership",
            required_role="server_lead",
        )
    ]

    assignments = generate_greedy_schedule(
        employees=employees,
        availability=availability,
        pto=[],
        shifts=shifts,
        role_cover_map={"server_lead": {"server_lead"}},
        exclude_owner=True,
    )
    assert assignments
    assert assignments[0].employee_id == "mgr"


def test_frontend_chat_sends_pending_intent_token_and_refreshes_new_run_queries():
    ai_chat_source = Path("frontend/src/components/AIChat.tsx").read_text(encoding="utf-8")
    dashboard_source = Path("frontend/src/pages/OwnerDashboard.tsx").read_text(encoding="utf-8")

    assert "pending_intent_token" in ai_chat_source
    assert "setPendingIntentToken(response.pending_intent_token)" in ai_chat_source
    assert "onScheduleRegenerated?.(response.new_schedule_run_id)" in ai_chat_source
    assert "invalidateQueries({ queryKey: ['latest-schedule-run', 'draft'] })" in dashboard_source
    assert "invalidateQueries({ queryKey: ['schedule-run'" in dashboard_source
    assert "invalidateQueries({ queryKey: ['schedule-metrics'" in dashboard_source
    assert "invalidateQueries({ queryKey: ['fairness-charts'" in dashboard_source
