from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import CoverageRequest, Employee, Shift
from ..schemas import (
    CoverageRequestCreate,
    CoverageRequestDecision,
    CoverageRequestResponse,
    CoverageRequestStatus,
)
from .auth import require_employee_or_owner, require_owner

router = APIRouter(prefix="/coverage-requests", tags=["coverage-requests"])


def _as_response(row: CoverageRequest) -> CoverageRequestResponse:
    return CoverageRequestResponse(
        id=row.id,
        requester_employee_id=row.requester_employee_id,
        shift_id=row.shift_id,
        status=CoverageRequestStatus(row.status),
        reason=row.reason,
        decision_note=row.decision_note,
        cover_employee_id=row.cover_employee_id,
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
        raise HTTPException(
            status_code=400,
            detail="employee_user_missing_employee_id",
        )
    return current_user


@router.post("", response_model=CoverageRequestResponse)
def create_coverage_request(
    request: CoverageRequestCreate,
    current_user=Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> CoverageRequestResponse:
    current_user = _require_employee_user(current_user)
    if request.requester_employee_id != current_user.employee_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Employees can only create requests for themselves"},
        )

    requester = session.get(Employee, request.requester_employee_id)
    if not requester:
        raise HTTPException(status_code=404, detail="employee_not_found")
    shift = session.get(Shift, request.shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="shift_not_found")

    row = CoverageRequest(
        requester_employee_id=request.requester_employee_id,
        shift_id=request.shift_id,
        status=CoverageRequestStatus.PENDING.value,
        reason=request.reason,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)


@router.get("/mine", response_model=list[CoverageRequestResponse])
def list_my_coverage_requests(
    current_user=Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> list[CoverageRequestResponse]:
    current_user = _require_employee_user(current_user)
    rows = session.exec(
        select(CoverageRequest)
        .where(CoverageRequest.requester_employee_id == current_user.employee_id)
        .order_by(CoverageRequest.created_at.desc())
    ).all()
    return [_as_response(row) for row in rows]


@router.get("/pending", response_model=list[CoverageRequestResponse])
def list_pending_coverage_requests(
    _owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> list[CoverageRequestResponse]:
    rows = session.exec(
        select(CoverageRequest)
        .where(CoverageRequest.status == CoverageRequestStatus.PENDING.value)
        .order_by(CoverageRequest.created_at.asc())
    ).all()
    return [_as_response(row) for row in rows]


@router.patch("/{request_id}/decision", response_model=CoverageRequestResponse)
def decide_coverage_request(
    request_id: int,
    decision: CoverageRequestDecision,
    _owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> CoverageRequestResponse:
    row = session.get(CoverageRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="coverage_request_not_found")

    if decision.cover_employee_id:
        cover_employee = session.get(Employee, decision.cover_employee_id)
        if not cover_employee:
            raise HTTPException(status_code=404, detail="cover_employee_not_found")

    row.status = decision.decision.value
    row.decision_note = decision.decision_note
    row.cover_employee_id = decision.cover_employee_id
    row.decided_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _as_response(row)
