from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Assignment as DbAssignment, ScheduleRun, Shift
from ..schemas import ScheduleMetricsResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/schedules/{schedule_run_id}", response_model=ScheduleMetricsResponse)
def get_schedule_metrics(
    schedule_run_id: int,
    session: Session = Depends(get_session),
) -> ScheduleMetricsResponse:
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="schedule_run_not_found")

    period_start = run.week_start_date
    period_end = period_start + timedelta(days=13)

    shifts = session.exec(
        select(Shift).where(Shift.date >= period_start, Shift.date <= period_end)
    ).all()
    shift_by_id = {s.id: s for s in shifts}

    db_assignments = session.exec(
        select(DbAssignment).where(DbAssignment.schedule_run_id == run.id)
    ).all()

    assigned_counts: dict[str, int] = {}
    for a in db_assignments:
        assigned_counts[a.shift_id] = assigned_counts.get(a.shift_id, 0) + 1

    understaffed = 0
    for shift_id, shift in shift_by_id.items():
        assigned = assigned_counts.get(shift_id, 0)
        if assigned < shift.required_staff:
            understaffed += 1

    total = len(shifts)
    coverage_percent = 100.0 if total == 0 else (100.0 * (total - understaffed) / total)

    violations = json.loads(run.violations_json)
    employee_fairness = json.loads(run.fairness_json)
    overall = float(run.overall_score or 0.0)

    return ScheduleMetricsResponse(
        schedule_run_id=run.id,
        period_start_date=period_start,
        period_days=14,
        mode=run.mode,
        status=run.status,
        total_shifts=total,
        understaffed_shifts=understaffed,
        coverage_percent=round(coverage_percent, 2),
        overall_fairness_percent=round(max(0.0, min(100.0, overall)), 2),
        employee_fairness=employee_fairness,
        violations=violations,
    )

