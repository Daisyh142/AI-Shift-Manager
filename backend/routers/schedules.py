from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import Assignment as DbAssignment, ScheduleRun, TimeOffRequest
from .auth import require_employee_or_owner, require_owner
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
import logging

from ..services.scheduling_service import generate_and_persist_schedule
from ..services.ai_service import generate_schedule_with_ai_orchestration

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def current_week_start() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _schedule_status_from_violations(violations: list[str]) -> str:
    hard_markers = (
        "UNDERSTAFFED_SHIFT:",
        "MISSING_MANAGER_COVERAGE:",
        "MISSING_CATEGORY_COVERAGE:",
        "MAX_DAYS_PER_WEEK_EXCEEDED:",
        "infeasible_",
    )
    return "infeasible" if any(v.startswith(hard_markers) for v in violations) else "success"


@router.get("/latest", response_model=ScheduleRunSummary)
def get_latest_schedule_run(
    status: str = Query(default="published", pattern="^(draft|published)$"),
    _current_user = Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunSummary:
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
    use_ai: bool = Query(default=True, description="Set false to skip AI analysis and return the schedule immediately."),
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    week_start = request.week_start_date or current_week_start()

    run_id, ai_summary = generate_schedule_with_ai_orchestration(
        session=session,
        week_start_date=week_start,
        mode=mode,
        use_ai=use_ai,
    )

    session.expire_all()

    run = session.get(ScheduleRun, run_id)
    if not run:
        logger.error("generate_schedule: run_id=%s not found after commit", run_id)
        raise HTTPException(status_code=500, detail="schedule_run_missing_after_generation")

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run_id)
    ).all()
    assignments = [
        Assignment(
            shift_id=a.shift_id,
            employee_id=a.employee_id,
            override=bool(getattr(a, "override", False)),
            override_reason=getattr(a, "override_reason", None),
        )
        for a in db_assignments
    ]

    violations = json.loads(run.violations_json)
    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        status=_schedule_status_from_violations(violations),
        assignments=assignments,
        violations=violations,
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )

    logger.info(
        "generate_schedule: returning run_id=%s assignments=%s violations=%s ai_summary_len=%s",
        run_id,
        len(assignments),
        len(violations),
        len(ai_summary or ""),
    )
    return ScheduleRunResponse(schedule_run_id=run_id, schedule=schedule, ai_summary=ai_summary)


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
    assignments = [
        Assignment(
            shift_id=a.shift_id,
            employee_id=a.employee_id,
            override=bool(getattr(a, "override", False)),
            override_reason=getattr(a, "override_reason", None),
        )
        for a in db_assignments
    ]

    violations = json.loads(run.violations_json)
    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        status=_schedule_status_from_violations(violations),
        assignments=assignments,
        violations=violations,
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )

    return ScheduleRunResponse(schedule_run_id=run.id, schedule=schedule)


@router.get("/{schedule_run_id}/fairness-charts", response_model=FairnessChartsResponse)
def get_fairness_charts(
    schedule_run_id: int,
    session: Session = Depends(get_session),
) -> FairnessChartsResponse:
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
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    run.status = "published"
    run.published_at = datetime.now(timezone.utc)
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
    prev = session.get(ScheduleRun, schedule_run_id)
    if not prev:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    run = generate_and_persist_schedule(
        session=session,
        week_start_date=prev.week_start_date,
        mode=prev.mode,
        redo_of_schedule_run_id=prev.id,
        redo_reason=request.reason,
        schedule_options={
            "exclude_owner": request.exclude_owner,
            "allow_max_days_override": request.allow_max_days_override,
        },
    )

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run.id)
    ).all()
    assignments = [
        Assignment(
            shift_id=a.shift_id,
            employee_id=a.employee_id,
            override=bool(getattr(a, "override", False)),
            override_reason=getattr(a, "override_reason", None),
        )
        for a in db_assignments
    ]

    violations = json.loads(run.violations_json)
    schedule = ScheduleResponse(
        week_start_date=run.week_start_date,
        status=_schedule_status_from_violations(violations),
        assignments=assignments,
        violations=violations,
        fairness_scores=json.loads(run.fairness_json),
        overall_score=run.overall_score,
    )
    return ScheduleRunResponse(schedule_run_id=run.id, schedule=schedule)


class OwnerRemoveEmployeeRequest(RedoScheduleRequest):
    employee_id: str
    start_date: str
    end_date: str


@router.post("/{schedule_run_id}/remove-employee", response_model=ScheduleRunResponse)
def owner_remove_employee_and_regenerate(
    schedule_run_id: int,
    request: OwnerRemoveEmployeeRequest,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ScheduleRunResponse:
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    try:
        start = datetime.fromisoformat(request.start_date).date()
        end = datetime.fromisoformat(request.end_date).date()
    except ValueError:
        print(
            f"[schedules] Invalid owner remove date range: start={request.start_date!r}, end={request.end_date!r}."
        )
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
                decided_at=datetime.now(timezone.utc),
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
        schedule_options={
            "exclude_owner": request.exclude_owner,
            "allow_max_days_override": request.allow_max_days_override,
        },
    )

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == new_run.id)
    ).all()
    assignments = [
        Assignment(
            shift_id=a.shift_id,
            employee_id=a.employee_id,
            override=bool(getattr(a, "override", False)),
            override_reason=getattr(a, "override_reason", None),
        )
        for a in db_assignments
    ]

    violations = json.loads(new_run.violations_json)
    schedule = ScheduleResponse(
        week_start_date=new_run.week_start_date,
        status=_schedule_status_from_violations(violations),
        assignments=assignments,
        violations=violations,
        fairness_scores=json.loads(new_run.fairness_json),
        overall_score=new_run.overall_score,
    )
    return ScheduleRunResponse(schedule_run_id=new_run.id, schedule=schedule)

