from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import Employee

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("", response_model=Employee)
def create_employee(employee: Employee, session: Session = Depends(get_session)) -> Employee:
    existing = session.exec(select(Employee).where(Employee.id == employee.id)).first()
    if existing:
        raise HTTPException(status_code=409, detail="employee_id_already_exists")

    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


@router.get("", response_model=list[Employee])
def list_employees(
    include_inactive: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[Employee]:
    query = select(Employee)
    if not include_inactive:
        query = query.where(Employee.active == True)  # noqa: E712
    return list(session.exec(query))


@router.get("/{employee_id}", response_model=Employee)
def get_employee(employee_id: str, session: Session = Depends(get_session)) -> Employee:
    employee = session.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="employee_not_found")
    return employee

