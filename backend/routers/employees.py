from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Employee

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("", response_model=Employee)
def create_employee(employee: Employee, session: Session = Depends(get_session)) -> Employee:
    """
    Creates an employee row in SQLite.

    Connection to the rest of the app:
    - The simulation script will call this logic (directly or indirectly) to load data.
    - The scheduler later reads employees from SQLite when generating schedules.
    """
    existing = session.exec(select(Employee).where(Employee.id == employee.id)).first()
    if existing:
        raise HTTPException(status_code=409, detail="employee_id_already_exists")

    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


@router.get("", response_model=list[Employee])
def list_employees(session: Session = Depends(get_session)) -> list[Employee]:
    return list(session.exec(select(Employee)))


@router.get("/{employee_id}", response_model=Employee)
def get_employee(employee_id: str, session: Session = Depends(get_session)) -> Employee:
    employee = session.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="employee_not_found")
    return employee

