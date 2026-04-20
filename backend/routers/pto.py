from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import TimeOffRequest
from ..schemas import TimeOffKind, TimeOffRequestCreate, TimeOffRequestResponse
from .auth import require_employee_or_owner
from .time_off import _as_response, create_time_off_request

router = APIRouter(prefix="/pto", tags=["pto"])


@router.post("", response_model=TimeOffRequestResponse)
def create_pto_request(
    request: TimeOffRequestCreate,
    current_user = Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> TimeOffRequestResponse:
    if request.kind != TimeOffKind.PTO:
        raise HTTPException(status_code=400, detail="use_time_off_endpoint_for_request_off")
    return create_time_off_request(request=request, current_user=current_user, session=session)


@router.get("", response_model=list[TimeOffRequestResponse])
def list_pto(
    current_user = Depends(require_employee_or_owner),
    session: Session = Depends(get_session),
) -> list[TimeOffRequestResponse]:
    rows = session.exec(
        select(TimeOffRequest).where(TimeOffRequest.kind == TimeOffKind.PTO.value)
    ).all()
    if current_user.role == "owner":
        return [_as_response(r) for r in rows]
    return [_as_response(r) for r in rows if r.employee_id == current_user.employee_id]

