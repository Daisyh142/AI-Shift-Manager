from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Shift

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.post("", response_model=Shift)
def create_shift(shift: Shift, session: Session = Depends(get_session)) -> Shift:
    existing = session.exec(select(Shift).where(Shift.id == shift.id)).first()
    if existing:
        raise HTTPException(status_code=409, detail="shift_id_already_exists")

    session.add(shift)
    session.commit()
    session.refresh(shift)
    return shift


@router.get("", response_model=list[Shift])
def list_shifts(session: Session = Depends(get_session)) -> list[Shift]:
    return list(session.exec(select(Shift)))

