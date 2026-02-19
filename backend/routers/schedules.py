from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import Assignment as DbAssignment, ScheduleRun, TimeOffRequest
from .auth import require_owner
from ..schemas import (
    Assignment,
    FairnessChartsResponse,
    GenerateDbScheduleRequest,
    ChartSlice,
    PublishScheduleResponse,
    RedoScheduleRequest,
    ScheduleRunSummary,
    TimeOffKind,
    TimeOffStatus,
    ScheduleResponse,
    ScheduleRunResponse,
)
from ..services.scheduling_service import build_period_inputs, generate_and_persist_schedule

router = APIRouter(prefix="/schedules", tags=["schedules"])


def current_week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


@router.get("/latest", response_model=ScheduleRunSummary)
def get_latest_schedule_run(
    status: str = Query(default="published", pattern="^(draft|published)$"),
    session: Session = Depends(get_session),
) -> ScheduleRunSummary:
    """
    Return the most recent schedule run for a given status.

    Frontend use:
    - employee pages request latest published run
    - owner pages can request latest draft run if needed
    """
    run = session.exec(
        select(ScheduleRun)
        .where(ScheduleRun.status == status)
        .order_by(ScheduleRun.created_at.desc())
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    return ScheduleRunSummary(
        schedule_run_id=run.id,
        week_start_date=run.week_start_date,
        mode=run.mode,
        status=run.status,
        published_at=run.published_at.isoformat() if run.published_at else None,
    )


@router.post("/generate", response_model=ScheduleRunResponse)
def generate_schedule_from_db(
    request: GenerateDbScheduleRequest,
    mode: str = Query(default="optimized", pattern="^(baseline|optimized)$"),
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    """
    Generates a schedule using data already stored in SQLite.

    Connection to the rest of the app:
    - Reads employees/availability/PTO/shifts from DB
    - Calls baseline or optimized scheduler
    - Persists schedule_run + assignments
    - Returns schedule JSON to the frontend
    """
    week_start = request.week_start_date or current_week_start()
    run = generate_and_persist_schedule(session=session, week_start_date=week_start, mode=mode)

    # Rebuild schedule response from DB so the API is a single source of truth.
    employees, availability, pto, shifts = build_period_inputs(session, week_start)
    _ = (employees, availability, pto, shifts)

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run.id)
    ).all()
    assignments = [Assignment(shift_id=a.shift_id, employee_id=a.employee_id) for a in db_assignments]

    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        assignments=assignments,
        violations=json.loads(run.violations_json),
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )

    return ScheduleRunResponse(schedule_run_id=run.id, schedule=schedule)


@router.get("/{schedule_run_id}", response_model=ScheduleRunResponse)
def get_schedule_run(
    schedule_run_id: int,
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run.id)
    ).all()
    assignments = [Assignment(shift_id=a.shift_id, employee_id=a.employee_id) for a in db_assignments]

    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        assignments=assignments,
        violations=json.loads(run.violations_json),
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )

    return ScheduleRunResponse(schedule_run_id=run.id, schedule=schedule)


@router.get("/{schedule_run_id}/fairness-charts", response_model=FairnessChartsResponse)
def get_fairness_charts(
    schedule_run_id: int,
    session: Session = Depends(get_session),
) -> FairnessChartsResponse:
    """
    Chart-ready fairness data for the frontend.

    Two pie charts:
    - overall: Fair vs Unmet (100 - overall_score)
    - employees: one slice per employee_id using their fairness percentage
    """
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    overall = float(run.overall_score or 0.0)
    overall_slices = [
        ChartSlice(label="fair", value=max(0.0, min(100.0, overall))),
        ChartSlice(label="unmet", value=max(0.0, 100.0 - max(0.0, min(100.0, overall)))),
    ]

    fairness_scores = json.loads(run.fairness_json)
    employee_slices = [
        ChartSlice(label=str(s.get("employee_id")), value=float(s.get("percentage", 0.0)))
        for s in fairness_scores
    ]

    return FairnessChartsResponse(overall=overall_slices, employees=employee_slices)


@router.post("/{schedule_run_id}/publish", response_model=PublishScheduleResponse)
def publish_schedule(
    schedule_run_id: int,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> PublishScheduleResponse:
    """
    Owner publishes a schedule after reviewing it.

    Connection to the rest of the app:
    - Frontend should show schedules in \"draft\" for owner review
    - Employees (later) should only see \"published\"
    """
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    run.status = "published"
    run.published_at = datetime.utcnow()
    session.add(run)
    session.commit()
    session.refresh(run)
    return PublishScheduleResponse(
        schedule_run_id=run.id,
        status=run.status,
        published_at=run.published_at.isoformat() if run.published_at else None,
    )


@router.post("/{schedule_run_id}/redo", response_model=ScheduleRunResponse)
def redo_schedule(
    schedule_run_id: int,
    request: RedoScheduleRequest,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    """
    Owner requests a redo (must provide a reason).

    Today this \"redo\" re-runs the scheduler. Later, when Gemini generation is added,
    this reason will also be fed into the prompt so the AI favors the owner's terms.
    """
    prev = session.get(ScheduleRun, schedule_run_id)
    if not prev:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    # Re-run using the same mode by default.
    run = generate_and_persist_schedule(
        session=session,
        week_start_date=prev.week_start_date,
        mode=prev.mode,
        redo_of_schedule_run_id=prev.id,
        redo_reason=request.reason,
    )

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run.id)
    ).all()
    assignments = [Assignment(shift_id=a.shift_id, employee_id=a.employee_id) for a in db_assignments]

    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        assignments=assignments,
        violations=json.loads(run.violations_json),
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )
    return ScheduleRunResponse(schedule_run_id=run.id, schedule=schedule)


class OwnerRemoveEmployeeRequest(RedoScheduleRequest):
    employee_id: str
    start_date: str  # ISO date
    end_date: str  # ISO date


@router.post("/{schedule_run_id}/remove-employee", response_model=ScheduleRunResponse)
def owner_remove_employee_and_regenerate(
    schedule_run_id: int,
    request: OwnerRemoveEmployeeRequest,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    """
    Owner removes an employee from a date range (reason required), then regenerates.

    Implementation approach:
    - We write APPROVED request_off rows into TimeOffRequest (owner override).
    - We then redo the schedule for that week, passing the owner's reason.
    """
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    try:
        start = datetime.fromisoformat(request.start_date).date()
        end = datetime.fromisoformat(request.end_date).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_date_format_use_iso")

    if end < start:
        raise HTTPException(status_code=400, detail="end_date_must_be_on_or_after_start_date")

    week_start = run.week_start_date
    week_end = week_start + timedelta(days=6)
    if start < week_start or end > week_end:
        raise HTTPException(status_code=400, detail="date_range_must_be_within_schedule_week")

    current = start
    while current <= end:
        session.add(
            TimeOffRequest(
                employee_id=request.employee_id,
                date=current,
                kind=TimeOffKind.REQUEST_OFF.value,
                status=TimeOffStatus.APPROVED.value,
                hours=0.0,
                reason=request.reason,
                decided_at=datetime.utcnow(),
            )
        )
        current = current + timedelta(days=1)

    session.commit()

    new_run = generate_and_persist_schedule(
        session=session,
        week_start_date=week_start,
        mode=run.mode,
        redo_of_schedule_run_id=run.id,
        redo_reason=request.reason,
    )

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == new_run.id)
    ).all()
    assignments = [Assignment(shift_id=a.shift_id, employee_id=a.employee_id) for a in db_assignments]

    schedule = ScheduleResponse(
        week_start_date=new_run.week_start_date,
        assignments=assignments,
        violations=json.loads(new_run.violations_json),
        fairness_scores=json.loads(new_run.fairness_json),
        overall_score=new_run.overall_score,
    )
    return ScheduleRunResponse(schedule_run_id=new_run.id, schedule=schedule)

