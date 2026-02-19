from __future__ import annotations

from datetime import date as Date, datetime as DateTime, time as Time
from typing import Optional

from sqlmodel import Field, SQLModel


class Employee(SQLModel, table=True):
    """
    A person who can be scheduled.

    Connects to:
    - Availability (when they can work)
    - PTO (when they cannot work)
    - Assignments (which shifts they were scheduled for)
    """

    id: str = Field(primary_key=True)  # we keep string IDs to match your current scheduler
    name: str

    # Scheduling constraints / preferences
    max_weekly_hours: float
    required_weekly_hours: float

    # Role + employment type drive priority (manager > shift_lead > regular, full_time > part_time)
    role: str = "regular"
    employment_type: str = "part_time"
    pto_balance_hours: float = 0.0
    category: str = Field(default="general", index=True)  # e.g. server, cook, host


class JobRole(SQLModel, table=True):
    """
    Job roles used for eligibility/coverage (cashier, barista, prep_cook, etc.).

    This is intentionally separate from `Employee.role`:
    - `Employee.role` is your *position* / hierarchy (manager, shift_lead, regular)
    - `JobRole` is the *work skill* / eligibility system (who can cover what)
    """

    name: str = Field(primary_key=True)


class JobRoleCanCover(SQLModel, table=True):
    """
    Directed edge: from_role -> to_role.

    Example: shift_lead_cashier can cover cashier.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    from_role: str = Field(foreign_key="jobrole.name", index=True)
    to_role: str = Field(foreign_key="jobrole.name", index=True)


class EmployeeJobRole(SQLModel, table=True):
    """Many-to-many link: which job roles an employee can perform."""

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    role_name: str = Field(foreign_key="jobrole.name", index=True)


class JobRoleCoverClosure(SQLModel, table=True):
    """
    Cached transitive closure for eligibility checks.

    For each required_role, store a JSON list of role names that can cover it.
    This avoids doing DFS at runtime for every eligibility check.
    """

    required_role: str = Field(primary_key=True)
    covers_json: str = "[]"
    computed_at: DateTime = Field(default_factory=DateTime.utcnow, index=True)


class Availability(SQLModel, table=True):
    """
    One availability window for an employee on a day of week.

    day_of_week matches Python's `date.weekday()` (0=Mon ... 6=Sun)
    so we can compare shifts to availability consistently.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    day_of_week: int  # 0..6
    start_time: Time
    end_time: Time


class TimeOffRequest(SQLModel, table=True):
    """
    A request to be unavailable on a given date.

    kind:
    - pto: paid time off (must have sufficient PTO balance hours)
    - request_off: unpaid request off

    status:
    - pending: waiting for owner approval
    - approved: treated as hard unavailability when scheduling
    - denied: ignored by scheduling
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: str = Field(foreign_key="employee.id", index=True)
    date: Date = Field(index=True)
    kind: str = Field(index=True)  # "pto" | "request_off"
    status: str = Field(index=True, default="pending")  # pending|approved|denied
    hours: float = 0.0
    reason: Optional[str] = None
    submitted_at: DateTime = Field(default_factory=DateTime.utcnow, index=True)
    decided_at: Optional[DateTime] = Field(default=None, index=True)


class Shift(SQLModel, table=True):
    """
    A single shift on a specific date.

    `required_staff` is used by analytics (understaffed shift rate).
    """

    id: str = Field(primary_key=True)
    date: Date = Field(index=True)
    start_time: Time
    end_time: Time
    required_role: Optional[str] = None
    required_staff: int = 2
    required_category: Optional[str] = Field(default=None, index=True)


class ScheduleRun(SQLModel, table=True):
    """
    One generated schedule for a specific week and mode.

    Connects to:
    - Assignments: the actual shift-to-employee mapping
    - Cached explanation: Gemini summary stored here to avoid repeat calls
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    week_start_date: Date = Field(index=True)
    mode: str = Field(index=True)  # baseline | optimized
    created_at: DateTime = Field(default_factory=DateTime.utcnow, index=True)

    # Owner workflow:
    # - draft: owner can review / redo
    # - published: visible to employees (when you build employee-facing UI)
    status: str = Field(default="draft", index=True)  # draft|published
    published_at: Optional[DateTime] = Field(default=None, index=True)

    redo_of_schedule_run_id: Optional[int] = Field(default=None, index=True)
    redo_reason: Optional[str] = None

    violations_json: str = "[]"
    fairness_json: str = "[]"
    overall_score: Optional[float] = None

    # Cached Gemini explanation text (low usage: 1 call, saved here)
    explanation_text: Optional[str] = None


class Assignment(SQLModel, table=True):
    """One employee assigned to one shift, belonging to a schedule run."""

    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_run_id: int = Field(foreign_key="schedulerun.id", index=True)
    shift_id: str = Field(foreign_key="shift.id", index=True)
    employee_id: str = Field(index=True)  # can be a real employee id or OWNER_ID


class User(SQLModel, table=True):
    """
    A login account.

    `role` controls what the frontend shows:
    - owner: sees all dashboards, fairness charts, can approve/deny requests
    - employee: sees own schedule, can submit time-off requests

    `employee_id` links to an Employee record.  For an owner account that is
    also a manager in the schedule it will point to their Employee row; for a
    pure owner account it can be None.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="employee", index=True)  # owner | employee
    employee_id: Optional[str] = Field(default=None, foreign_key="employee.id")


class AIDecisionLog(SQLModel, table=True):
    """
    Auditable trace for AI suggestions and owner outcomes.

    This is intentionally append-only and does not drive scheduling behavior.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: DateTime = Field(default_factory=DateTime.utcnow, index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    message: str
    recommendation_type: Optional[str] = Field(default=None, index=True)
    action_type: Optional[str] = Field(default=None, index=True)
    owner_decision: Optional[str] = Field(default=None, index=True)  # suggested | confirmed | rejected

    schedule_run_id: Optional[int] = Field(default=None, index=True)
    fairness_before: Optional[float] = None
    fairness_after: Optional[float] = None
    outcome_json: str = "{}"

