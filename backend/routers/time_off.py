from __future__ import annotations

import math
import os
from datetime import date as Date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from ..db import get_session
from ..models import Employee, TimeOffRequest
from ..priority_graph import employee_priority_score
from .auth import require_employee_or_owner, require_owner
from ..schemas import TimeOffKind, TimeOffRequestCreate, TimeOffRequestResponse, TimeOffStatus

router = APIRouter(prefix="/time-off", tags=["time-off"])

DEFAULT_MIN_AVAILABLE_RATIO = 0.75  # 75% of employees must remain available


def _min_available_ratio() -> float:
    raw = os.getenv("TIME_OFF_MIN_AVAILABLE_RATIO", str(DEFAULT_MIN_AVAILABLE_RATIO))
    try:
        value = float(raw)
    except ValueError:
        print(f"[time_off] Invalid TIME_OFF_MIN_AVAILABLE_RATIO={raw!r}; using default {DEFAULT_MIN_AVAILABLE_RATIO}.")
        value = DEFAULT_MIN_AVAILABLE_RATIO
    return max(0.0, min(1.0, value))


def _employee_priority(employee: Employee) -> int:
    return employee_priority_score(role=employee.role, employment_type=employee.employment_type)


def _as_response(r: TimeOffRequest) -> TimeOffRequestResponse:
    return TimeOffRequestResponse(
        id=r.id,
        employee_id=r.employee_id,
        date=r.date,
        kind=TimeOffKind(r.kind),
        status=TimeOffStatus(r.status),
        hours=r.hours,
        reason=r.reason,
        submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        decided_at=r.decided_at.isoformat() if r.decided_at else None,
    )


@router.post("/requests", response_model=TimeOffRequestResponse)
def create_time_off_request(
    request: TimeOffRequestCreate,
    current_user = Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> TimeOffRequestResponse:
    if current_user.role == "employee" and current_user.employee_id != request.employee_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Employees can only create requests for themselves"},
        )

    employee = session.get(Employee, request.employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="employee_not_found")

    today = Date.today()
    if request.date < today + timedelta(days=14):
        raise HTTPException(status_code=400, detail="time_off_must_be_2_weeks_in_advance")

    if request.kind == TimeOffKind.PTO:
        if request.hours <= 0:
            raise HTTPException(status_code=400, detail="pto_hours_required")
        if employee.pto_balance_hours < request.hours:
            raise HTTPException(status_code=400, detail="insufficient_pto_use_request_off")

    existing = session.exec(
        select(TimeOffRequest).where(
            TimeOffRequest.employee_id == request.employee_id,
            TimeOffRequest.date == request.date,
            TimeOffRequest.kind == request.kind.value,
            TimeOffRequest.status.in_(
                [TimeOffStatus.PENDING.value, TimeOffStatus.APPROVED.value]
            ),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="duplicate_time_off_request_exists")

    row = TimeOffRequest(
        employee_id=request.employee_id,
        date=request.date,
        kind=request.kind.value,
        status=TimeOffStatus.PENDING.value,
        hours=request.hours,
        reason=request.reason,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)


@router.get("/requests", response_model=list[TimeOffRequestResponse])
def list_time_off_requests(
    current_user = Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> list[TimeOffRequestResponse]:
    rows = session.exec(select(TimeOffRequest).order_by(TimeOffRequest.date.desc())).all()
    if current_user.role == "owner":
        return [_as_response(r) for r in rows]
    return [_as_response(r) for r in rows if r.employee_id == current_user.employee_id]


@router.post("/requests/{request_id}/approve", response_model=TimeOffRequestResponse)
def approve_time_off(
    request_id: int,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> TimeOffRequestResponse:
    row = session.get(TimeOffRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")

    if row.status == TimeOffStatus.APPROVED.value:
        return _as_response(row)

    if row.date < Date.today():
        raise HTTPException(status_code=400, detail="cannot_approve_past_time_off_request")

    employee = session.get(Employee, row.employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="employee_not_found")

    employees_in_category = session.exec(
        select(Employee).where(Employee.category == employee.category)
    ).all()
    total_employees = len(employees_in_category)
    if total_employees > 0:
        min_available_ratio = _min_available_ratio()
        min_available_count = int(math.ceil(total_employees * min_available_ratio))
        max_time_off_count = max(0, total_employees - min_available_count)

        employee_ids_in_category = {e.id for e in employees_in_category}
        requests_for_date = session.exec(
            select(TimeOffRequest).where(
                TimeOffRequest.date == row.date,
                TimeOffRequest.status.in_(
                    [TimeOffStatus.PENDING.value, TimeOffStatus.APPROVED.value]
                ),
            )
        ).all()

        requests_for_date = [r for r in requests_for_date if r.employee_id in employee_ids_in_category]
        employee_by_id = {e.id: e for e in employees_in_category}

        def _req_sort_key(r: TimeOffRequest):
            e = employee_by_id.get(r.employee_id)
            if not e:
                return (0, r.submitted_at)
            return (-_employee_priority(e), r.submitted_at)

        requests_for_date.sort(key=_req_sort_key)

        allowed_ids = {r.id for r in requests_for_date[:max_time_off_count]}
        if row.id not in allowed_ids:
            raise HTTPException(
                status_code=400,
                detail="time_off_capacity_reached_keep_75_percent_available",
            )

    if row.kind == TimeOffKind.PTO.value:
        stmt = (
            update(Employee)
            .where(Employee.id == employee.id, Employee.pto_balance_hours >= row.hours)
            .values(pto_balance_hours=Employee.pto_balance_hours - row.hours)
        )
        result = session.exec(stmt)
        if (result.rowcount or 0) == 0:
            raise HTTPException(status_code=400, detail="cannot_approve_pto_insufficient_balance")
        session.flush()

    row.status = TimeOffStatus.APPROVED.value
    row.decided_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)


@router.post("/requests/{request_id}/deny", response_model=TimeOffRequestResponse)
def deny_time_off(
    request_id: int,
    _owner = Depends(require_owner),
    session: Session = Depends(get_session),
) -> TimeOffRequestResponse:
    row = session.get(TimeOffRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="request_not_found")

    row.status = TimeOffStatus.DENIED.value
    row.decided_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)

