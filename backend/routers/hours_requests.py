from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Employee, EmployeeHoursPreference, HoursChangeRequest
from ..schemas import HoursRequestCreate, HoursRequestDecision, HoursRequestResponse, HoursRequestStatus
from .auth import require_employee_or_owner, require_owner

router = APIRouter(prefix="/hours-requests", tags=["hours-requests"])


def _as_response(row: HoursChangeRequest) -> HoursRequestResponse:
    return HoursRequestResponse(
        id=row.id,
        employee_id=row.employee_id,
        period_start=row.period_start,
        period_end=row.period_end,
        requested_hours=row.requested_hours,
        status=HoursRequestStatus(row.status),
        note=row.note,
        created_at=row.created_at.isoformat() if row.created_at else None,
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
    )


def _require_employee_user(current_user):
    if current_user.role != "employee":
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Employee role is required"},
        )
    if not current_user.employee_id:
        raise HTTPException(status_code=400, detail="employee_user_missing_employee_id")
    return current_user


@router.post("", response_model=HoursRequestResponse)
def create_hours_request(
    request: HoursRequestCreate,
    current_user=Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> HoursRequestResponse:
    current_user = _require_employee_user(current_user)
    if request.employee_id != current_user.employee_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Employees can only create requests for themselves"},
        )
    employee = session.get(Employee, request.employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="employee_not_found")
    if request.period_end != request.period_start + timedelta(days=13):
        raise HTTPException(status_code=400, detail="hours_request_period_must_be_14_days")

    duplicate_pending = session.exec(
        select(HoursChangeRequest).where(
            HoursChangeRequest.employee_id == request.employee_id,
            HoursChangeRequest.period_start == request.period_start,
            HoursChangeRequest.period_end == request.period_end,
            HoursChangeRequest.status == HoursRequestStatus.PENDING.value,
        )
    ).first()
    if duplicate_pending:
        raise HTTPException(status_code=409, detail="duplicate_pending_hours_request_exists")

    row = HoursChangeRequest(
        employee_id=request.employee_id,
        period_start=request.period_start,
        period_end=request.period_end,
        requested_hours=request.requested_hours,
        status=HoursRequestStatus.PENDING.value,
        note=request.note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)


@router.get("/mine", response_model=list[HoursRequestResponse])
def list_my_hours_requests(
    current_user=Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> list[HoursRequestResponse]:
    current_user = _require_employee_user(current_user)
    rows = session.exec(
        select(HoursChangeRequest)
        .where(HoursChangeRequest.employee_id == current_user.employee_id)
        .order_by(HoursChangeRequest.created_at.desc())
    ).all()
    return [_as_response(row) for row in rows]


@router.get("/pending", response_model=list[HoursRequestResponse])
def list_pending_hours_requests(
    _owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> list[HoursRequestResponse]:
    rows = session.exec(
        select(HoursChangeRequest)
        .where(HoursChangeRequest.status == HoursRequestStatus.PENDING.value)
        .order_by(HoursChangeRequest.created_at.asc())
    ).all()
    return [_as_response(row) for row in rows]


@router.patch("/{request_id}/decision", response_model=HoursRequestResponse)
def decide_hours_request(
    request_id: int,
    decision: HoursRequestDecision,
    _owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> HoursRequestResponse:
    row = session.get(HoursChangeRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="hours_request_not_found")
    if decision.decision not in {HoursRequestStatus.APPROVED, HoursRequestStatus.DENIED}:
        raise HTTPException(status_code=400, detail="decision_must_be_approved_or_denied")

    row.status = decision.decision.value
    row.decided_at = datetime.now(timezone.utc)
    session.add(row)

    if decision.decision == HoursRequestStatus.APPROVED:
        preference = session.exec(
            select(EmployeeHoursPreference).where(
                EmployeeHoursPreference.employee_id == row.employee_id,
                EmployeeHoursPreference.period_start == row.period_start,
                EmployeeHoursPreference.period_end == row.period_end,
            )
        ).first()
        if preference:
            preference.requested_hours = row.requested_hours
            session.add(preference)
        else:
            session.add(
                EmployeeHoursPreference(
                    employee_id=row.employee_id,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    requested_hours=row.requested_hours,
                )
            )

    session.commit()
    session.refresh(row)
    return _as_response(row)
