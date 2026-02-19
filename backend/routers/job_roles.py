from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..coverage import recompute_job_role_closure
from ..db import get_session
from ..models import Employee, EmployeeJobRole, JobRole, JobRoleCanCover

router = APIRouter(prefix="/job-roles", tags=["job-roles"])


@router.post("", response_model=JobRole)
def create_job_role(role: JobRole, session: Session = Depends(get_session)) -> JobRole:
    existing = session.get(JobRole, role.name)
    if existing:
        raise HTTPException(status_code=409, detail="job_role_already_exists")
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


@router.get("", response_model=list[JobRole])
def list_job_roles(session: Session = Depends(get_session)) -> list[JobRole]:
    return list(session.exec(select(JobRole)))


@router.post("/edges", response_model=JobRoleCanCover)
def create_job_role_edge(
    edge: JobRoleCanCover, session: Session = Depends(get_session)
) -> JobRoleCanCover:
    # Validate endpoints exist
    if not session.get(JobRole, edge.from_role) or not session.get(JobRole, edge.to_role):
        raise HTTPException(status_code=400, detail="unknown_job_role_in_edge")

    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


@router.get("/edges", response_model=list[JobRoleCanCover])
def list_job_role_edges(session: Session = Depends(get_session)) -> list[JobRoleCanCover]:
    return list(session.exec(select(JobRoleCanCover)))


@router.post("/assign", response_model=EmployeeJobRole)
def assign_job_role_to_employee(
    assignment: EmployeeJobRole, session: Session = Depends(get_session)
) -> EmployeeJobRole:
    if not session.get(Employee, assignment.employee_id):
        raise HTTPException(status_code=404, detail="employee_not_found")
    if not session.get(JobRole, assignment.role_name):
        raise HTTPException(status_code=404, detail="job_role_not_found")

    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


@router.get("/assign", response_model=list[EmployeeJobRole])
def list_employee_job_roles(
    employee_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[EmployeeJobRole]:
    stmt = select(EmployeeJobRole)
    if employee_id:
        stmt = stmt.where(EmployeeJobRole.employee_id == employee_id)
    return list(session.exec(stmt))


@router.post("/recompute-closure", response_model=dict)
def recompute_closure(session: Session = Depends(get_session)) -> dict:
    count = recompute_job_role_closure(session)
    return {"roles_processed": count}

