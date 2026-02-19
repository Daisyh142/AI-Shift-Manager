from __future__ import annotations

"""
Legacy PTO routes.

We keep these temporarily, but the new system is:
- POST /time-off/requests  (kind=pto or request_off)
- Owner approve/deny endpoints
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import TimeOffRequest
from ..schemas import TimeOffKind, TimeOffRequestCreate, TimeOffRequestResponse, TimeOffStatus
from .time_off import _as_response, create_time_off_request

router = APIRouter(prefix="/pto", tags=["pto"])


@router.post("", response_model=TimeOffRequestResponse)
def create_pto_request(
    request: TimeOffRequestCreate, session: Session = Depends(get_session)
) -> TimeOffRequestResponse:
    if request.kind != TimeOffKind.PTO:
        raise HTTPException(status_code=400, detail="use_time_off_endpoint_for_request_off")
    return create_time_off_request(request, session)


@router.get("", response_model=list[TimeOffRequestResponse])
def list_pto(session: Session = Depends(get_session)) -> list[TimeOffRequestResponse]:
    rows = session.exec(
        select(TimeOffRequest).where(TimeOffRequest.kind == TimeOffKind.PTO.value)
    ).all()
    return [_as_response(r) for r in rows]

