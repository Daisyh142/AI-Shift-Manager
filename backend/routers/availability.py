from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..models import Availability

router = APIRouter(prefix="/availability", tags=["availability"])


@router.post("", response_model=Availability)
def create_availability(
    availability: Availability, session: Session = Depends(get_session)
) -> Availability:
    session.add(availability)
    session.commit()
    session.refresh(availability)
    return availability


@router.get("", response_model=list[Availability])
def list_availability(session: Session = Depends(get_session)) -> list[Availability]:
    return list(session.exec(select(Availability)))

