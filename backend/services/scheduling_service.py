from __future__ import annotations

import json
from datetime import date, timedelta

from sqlmodel import Session, select

from ..baseline_scheduler import generate_baseline_schedule
from ..constraints import validate_assignments
from ..fairness import calculate_fairness
from ..models import (
    Assignment as DbAssignment,
    Availability as DbAvailability,
    Employee as DbEmployee,
    EmployeeJobRole as DbEmployeeJobRole,
    ScheduleRun,
    Shift as DbShift,
    TimeOffRequest as DbTimeOffRequest,
)
from ..schemas import (
    Assignment,
    Availability,
    Employee,
    EmploymentType,
    PTO,
    Role,
    Shift,
    TimeOffKind,
    TimeOffStatus,
)
from ..scheduler import generate_greedy_schedule
from ..coverage import cover_set_for_required_role


def _to_schema_employee(e: DbEmployee, job_roles: list[str]) -> Employee:
    try:
        role = Role(e.role)
    except ValueError:
        role = Role.REGULAR

    try:
        employment_type = EmploymentType(e.employment_type)
    except ValueError:
        employment_type = EmploymentType.PART_TIME

    return Employee(
        id=e.id,
        name=e.name,
        max_weekly_hours=e.max_weekly_hours,
        required_weekly_hours=e.required_weekly_hours,
        role=role,
        employment_type=employment_type,
        pto_balance_hours=e.pto_balance_hours,
        category=e.category,
        job_roles=job_roles,
    )


def _to_schema_availability(a: DbAvailability) -> Availability:
    return Availability(
        employee_id=a.employee_id,
        day_of_week=a.day_of_week,
        start_time=a.start_time,
        end_time=a.end_time,
    )


def _to_schema_time_off(p: DbTimeOffRequest) -> PTO:
    # We reuse the existing scheduler/validator "PTO list" concept as
    # "approved time off" (paid or unpaid).
    kind = TimeOffKind(p.kind) if p.kind in TimeOffKind._value2member_map_ else TimeOffKind.REQUEST_OFF
    return PTO(
        employee_id=p.employee_id,
        date=p.date,
        kind=kind,
        hours=p.hours,
        reason=p.reason,
    )


def _to_schema_shift(s: DbShift) -> Shift:
    return Shift(
        id=s.id,
        date=s.date,
        start_time=s.start_time,
        end_time=s.end_time,
        required_role=s.required_role,
        required_staff=s.required_staff,
        required_category=s.required_category,
    )


def build_period_inputs(session: Session, period_start_date: date) -> tuple[
    list[Employee], list[Availability], list[PTO], list[Shift]
]:
    """
    Reads SQLite tables and converts them into the Pydantic objects the scheduler expects.

    Connection to the rest of the app:
    - Routers call this to gather inputs.
    - Schedulers operate only on these Pydantic lists (pure Python, easy to test).
    """
    employee_rows = session.exec(select(DbEmployee)).all()
    job_role_rows = session.exec(select(DbEmployeeJobRole)).all()
    job_roles_by_employee: dict[str, list[str]] = {}
    for r in job_role_rows:
        job_roles_by_employee.setdefault(r.employee_id, []).append(r.role_name)

    employees = [
        _to_schema_employee(e, job_roles=sorted(job_roles_by_employee.get(e.id, [])))
        for e in employee_rows
    ]
    availability = [
        _to_schema_availability(a) for a in session.exec(select(DbAvailability)).all()
    ]
    period_end = period_start_date + timedelta(days=13)
    pto = [
        _to_schema_time_off(p)
        for p in session.exec(
            select(DbTimeOffRequest).where(
                DbTimeOffRequest.status == TimeOffStatus.APPROVED.value,
                DbTimeOffRequest.date >= period_start_date,
                DbTimeOffRequest.date <= period_end,
            )
        ).all()
    ]

    shifts = [
        _to_schema_shift(s)
        for s in session.exec(
            select(DbShift).where(DbShift.date >= period_start_date, DbShift.date <= period_end)
        ).all()
    ]

    # Stable ordering so outputs are reproducible.
    shifts.sort(key=lambda s: (s.date, s.start_time, s.id))
    return employees, availability, pto, shifts


def generate_and_persist_schedule(
    *,
    session: Session,
    week_start_date: date,
    mode: str,
    redo_of_schedule_run_id: int | None = None,
    redo_reason: str | None = None,
) -> ScheduleRun:
    """
    Orchestrates schedule generation.

    Connection map (end-to-end):
    - API endpoint calls this function
    - It reads inputs from SQLite
    - Runs baseline or optimized scheduler (pure Python)
    - Validates hard constraints
    - Computes fairness scores
    - Persists ScheduleRun + Assignment rows back into SQLite
    """
    employees, availability, pto, shifts = build_period_inputs(session, week_start_date)

    required_roles = sorted({s.required_role for s in shifts if s.required_role})
    role_cover_map = {r: cover_set_for_required_role(session, r) for r in required_roles}

    if mode == "baseline":
        assignments = generate_baseline_schedule(
            week_start_seed=week_start_date.toordinal(),
            employees=employees,
            availability=availability,
            pto=pto,
            shifts=shifts,
            role_cover_map=role_cover_map,
        )
    elif mode == "optimized":
        assignments = generate_greedy_schedule(
            employees=employees,
            availability=availability,
            pto=pto,
            shifts=shifts,
            role_cover_map=role_cover_map,
        )
    else:
        raise ValueError("mode_must_be_baseline_or_optimized")

    violations = validate_assignments(
        employees=employees,
        availability=availability,
        pto=pto,
        shifts=shifts,
        assignments=assignments,
        role_cover_map=role_cover_map,
    )

    unique_shift_days = sorted({s.date for s in shifts})
    if unique_shift_days:
        period_days = (unique_shift_days[-1] - unique_shift_days[0]).days + 1
    else:
        period_days = 7
    weeks_in_period = max(1.0, period_days / 7.0)

    fairness_scores = calculate_fairness(
        employees=employees,
        shifts=shifts,
        assignments=assignments,
        weeks_in_period=weeks_in_period,
    )
    overall_score = (
        sum(s.percentage for s in fairness_scores) / len(fairness_scores) if fairness_scores else 0.0
    )

    run = ScheduleRun(
        week_start_date=week_start_date,
        mode=mode,
        redo_of_schedule_run_id=redo_of_schedule_run_id,
        redo_reason=redo_reason,
        violations_json=json.dumps(violations),
        fairness_json=json.dumps([s.model_dump() for s in fairness_scores]),
        overall_score=overall_score,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for a in assignments:
        session.add(
            DbAssignment(
                schedule_run_id=run.id,
                shift_id=a.shift_id,
                employee_id=a.employee_id,
            )
        )
    session.commit()

    return run

