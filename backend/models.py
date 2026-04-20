from __future__ import annotations

from datetime import date as Date, datetime as DateTime, time as Time, timezone
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint


def _utc_now() -> DateTime:
    return DateTime.now(timezone.utc)


class Employee(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    max_weekly_hours: float
    required_weekly_hours: float
    role: str = "regular"
    employment_type: str = "part_time"
    active: bool = Field(default=True, index=True)
    pto_balance_hours: float = 0.0
    category: str = Field(default="general", index=True)


class JobRole(SQLModel, table=True):
    name: str = Field(primary_key=True)


class JobRoleCanCover(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_role: str = Field(foreign_key="jobrole.name", index=True)
    to_role: str = Field(foreign_key="jobrole.name", index=True)


class EmployeeJobRole(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    role_name: str = Field(foreign_key="jobrole.name", index=True)


class JobRoleCoverClosure(SQLModel, table=True):
    required_role: str = Field(primary_key=True)
    covers_json: str = "[]"
    computed_at: DateTime = Field(default_factory=_utc_now, index=True)


class Availability(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    day_of_week: int
    start_time: Time
    end_time: Time


class TimeOffRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    date: Date = Field(index=True)
    kind: str = Field(index=True)
    status: str = Field(index=True, default="pending")
    hours: float = 0.0
    reason: Optional[str] = None
    submitted_at: DateTime = Field(default_factory=_utc_now, index=True)
    decided_at: Optional[DateTime] = Field(default=None, index=True)


class CoverageRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    requester_employee_id: str = Field(foreign_key="employee.id", index=True)
    shift_id: str = Field(foreign_key="shift.id", index=True)
    status: str = Field(default="pending", index=True)
    reason: Optional[str] = None
    decision_note: Optional[str] = None
    cover_employee_id: Optional[str] = Field(default=None, foreign_key="employee.id", index=True)
    created_at: DateTime = Field(default_factory=_utc_now, index=True)
    decided_at: Optional[DateTime] = Field(default=None, index=True)


class HoursChangeRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    period_start: Date = Field(index=True)
    period_end: Date = Field(index=True)
    requested_hours: int
    status: str = Field(default="pending", index=True)
    note: Optional[str] = None
    created_at: DateTime = Field(default_factory=_utc_now, index=True)
    decided_at: Optional[DateTime] = Field(default=None, index=True)


class EmployeeHoursPreference(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("employee_id", "period_start", "period_end"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    period_start: Date = Field(index=True)
    period_end: Date = Field(index=True)
    requested_hours: int
    created_at: DateTime = Field(default_factory=_utc_now, index=True)


class Shift(SQLModel, table=True):
    id: str = Field(primary_key=True)
    date: Date = Field(index=True)
    start_time: Time
    end_time: Time
    required_role: Optional[str] = None
    required_staff: int = 2
    required_category: Optional[str] = Field(default=None, index=True)


class ScheduleRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    week_start_date: Date = Field(index=True)
    mode: str = Field(index=True)
    created_at: DateTime = Field(default_factory=_utc_now, index=True)
    status: str = Field(default="draft", index=True)
    published_at: Optional[DateTime] = Field(default=None, index=True)

    redo_of_schedule_run_id: Optional[int] = Field(default=None, index=True)
    redo_reason: Optional[str] = None

    violations_json: str = "[]"
    fairness_json: str = "[]"
    overall_score: Optional[float] = None

    explanation_text: Optional[str] = None


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_run_id: int = Field(foreign_key="schedulerun.id", index=True)
    shift_id: str = Field(foreign_key="shift.id", index=True)
    employee_id: str = Field(index=True)
    override: bool = Field(default=False, index=True)
    override_reason: Optional[str] = Field(default=None, index=True)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="employee", index=True)
    employee_id: Optional[str] = Field(default=None, foreign_key="employee.id")


class AIDecisionLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: DateTime = Field(default_factory=_utc_now, index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    message: str
    recommendation_type: Optional[str] = Field(default=None, index=True)
    action_type: Optional[str] = Field(default=None, index=True)
    owner_decision: Optional[str] = Field(default=None, index=True)

    schedule_run_id: Optional[int] = Field(default=None, index=True)
    fairness_before: Optional[float] = None
    fairness_after: Optional[float] = None
    outcome_json: str = "{}"

