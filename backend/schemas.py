from __future__ import annotations
from datetime import date, time
from typing import Any, List, Optional, Dict, Literal
from pydantic import BaseModel, Field
from enum import Enum

class Role(str, Enum):
    OWNER = "owner"
    MANAGER = "manager"
    SHIFT_LEAD = "shift_lead"
    REGULAR = "regular"

class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"

class TimeOffKind(str, Enum):
    PTO = "pto"  # paid time off (uses PTO balance)
    REQUEST_OFF = "request_off"  # unpaid request off


class TimeOffStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class CoverageRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class HoursRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class Employee(BaseModel):
    id: str
    name: str
    max_weekly_hours: float = Field(ge=0)
    required_weekly_hours: float = Field(ge=0)
    role: Role = Role.REGULAR
    employment_type: EmploymentType = EmploymentType.PART_TIME
    active: bool = True
    pto_balance_hours: float = Field(default=0, ge=0)
    category: str = Field(default="general", min_length=1)
    job_roles: List[str] = []

class Availability(BaseModel):
    employee_id: str
    day_of_week: int = Field(ge=0, le=6)  # 0=Mon ... 6=Sun (matches Python date.weekday())
    start_time: time
    end_time: time

class PTO(BaseModel):
    employee_id: str
    date: date
    kind: TimeOffKind = TimeOffKind.PTO
    hours: float = Field(default=0, ge=0)
    reason: Optional[str] = None

class Shift(BaseModel):
    id: str
    date: date
    start_time: time
    end_time: time
    required_role: Optional[str] = None
    required_staff: int = Field(default=2, ge=1)
    required_category: Optional[str] = None

class Assignment(BaseModel):
    shift_id: str
    employee_id: str
    override: bool = False
    override_reason: Optional[str] = None

class GenerateScheduleRequest(BaseModel):
    week_start_date: date
    employees: List[Employee]
    availability: List[Availability]
    pto: List[PTO]
    shifts: List[Shift]
    weekend_history: Optional[Dict[str, int]] = None

class FairnessScore(BaseModel):
    employee_id: str
    percentage: float = Field(ge=0, le=100)
    reasoning: List[str]
    assigned_hours: float = Field(default=0, ge=0)
    requested_hours: float = Field(default=0, ge=0)
    delta_hours: float = 0
    max_hours: float = Field(default=0, ge=0)
    utilization: float = Field(default=0, ge=0, le=1)


class ScheduleChangeConstraints(BaseModel):
    prefer_shift_ranges: list[str] = Field(default_factory=list)
    avoid_shift_ranges: list[str] = Field(default_factory=list)
    max_days_per_week: int | None = Field(default=None, ge=1, le=7)


class ScheduleChangeRequest(BaseModel):
    type: Literal["ADJUST_HOURS", "SET_UTILIZATION_TARGET"]
    employee_id: str
    period_start: date
    delta_hours: float | None = None
    target_utilization: float | None = Field(default=None, ge=0, le=1)
    strict: bool = False
    tradeoff_policy: str = "LOWEST_PRIORITY_LOSES_FIRST"
    constraints: ScheduleChangeConstraints = Field(default_factory=ScheduleChangeConstraints)
    reason: str = Field(min_length=1)

class ScheduleResponse(BaseModel):
    week_start_date: date
    status: str = "success"  
    assignments: List[Assignment]
    violations: List[str]
    fairness_scores: List[FairnessScore] = []
    overall_score: Optional[float] = None


class GenerateDbScheduleRequest(BaseModel):
    week_start_date: Optional[date] = None


class ScheduleRunResponse(BaseModel):
    schedule_run_id: int
    schedule: ScheduleResponse
    ai_summary: Optional[str] = None


class ScheduleRunSummary(BaseModel):
    schedule_run_id: int
    week_start_date: date
    mode: str
    status: str
    published_at: Optional[str] = None


class RedoScheduleRequest(BaseModel):
    reason: str = Field(min_length=1)
    exclude_owner: Optional[bool] = None
    allow_max_days_override: Optional[bool] = None


class PublishScheduleResponse(BaseModel):
    schedule_run_id: int
    status: str
    published_at: Optional[str] = None


class TimeOffRequestCreate(BaseModel):
    employee_id: str
    date: date
    kind: TimeOffKind
    hours: float = Field(default=0, ge=0)
    reason: Optional[str] = None


class TimeOffRequestResponse(BaseModel):
    id: int
    employee_id: str
    date: date
    kind: TimeOffKind
    status: TimeOffStatus
    hours: float
    reason: Optional[str] = None
    submitted_at: Optional[str] = None
    decided_at: Optional[str] = None


class CoverageRequestCreate(BaseModel):
    requester_employee_id: str
    shift_id: str
    reason: Optional[str] = None


class CoverageRequestDecision(BaseModel):
    decision: CoverageRequestStatus
    decision_note: Optional[str] = None
    cover_employee_id: Optional[str] = None


class CoverageRequestResponse(BaseModel):
    id: int
    requester_employee_id: str
    shift_id: str
    status: CoverageRequestStatus
    reason: Optional[str] = None
    decision_note: Optional[str] = None
    cover_employee_id: Optional[str] = None
    created_at: Optional[str] = None
    decided_at: Optional[str] = None


class HoursRequestCreate(BaseModel):
    employee_id: str
    period_start: date
    period_end: date
    requested_hours: int = Field(ge=0, le=80)
    note: Optional[str] = None


class HoursRequestDecision(BaseModel):
    decision: HoursRequestStatus
    decision_note: Optional[str] = None


class HoursRequestResponse(BaseModel):
    id: int
    employee_id: str
    period_start: date
    period_end: date
    requested_hours: int
    status: HoursRequestStatus
    note: Optional[str] = None
    created_at: Optional[str] = None
    decided_at: Optional[str] = None


class ChartSlice(BaseModel):
    label: str
    value: float = Field(ge=0)


class FairnessChartsResponse(BaseModel):
    overall: list[ChartSlice]
    employees: list[ChartSlice]


class ScheduleMetricsResponse(BaseModel):
    schedule_run_id: int
    period_start_date: date
    period_days: int
    mode: str
    status: str

    total_shifts: int
    understaffed_shifts: int
    coverage_percent: float = Field(ge=0, le=100)

    overall_fairness_percent: float = Field(ge=0, le=100)
    employee_fairness: list[FairnessScore]
    violations: list[str]


class UserRole(str, Enum):
    OWNER = "owner"
    EMPLOYEE = "employee"


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=4)
    role: UserRole = UserRole.EMPLOYEE
    employee_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: UserRole
    employee_id: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class OwnerRemoveEmployeeRequest(BaseModel):
    employee_id: str
    start_date: str
    end_date: str
    reason: str = Field(min_length=1)

class AIRecommendationType(str, Enum):
    RECOMMEND_TIME_OFF_DECISION = "recommend_time_off_decision"
    ANALYZE_COVERAGE_CONFLICTS = "analyze_coverage_conflicts"
    EXPLAIN_SCHEDULE_FAIRNESS = "explain_schedule_fairness"
    PROPOSE_REGENERATION_PARAMETERS = "propose_regeneration_parameters"


class AIActionType(str, Enum):
    REDO_SCHEDULE = "redo_schedule"
    APPROVE_TIME_OFF = "approve_time_off"
    DENY_TIME_OFF = "deny_time_off"
    REMOVE_EMPLOYEE_AND_REGENERATE = "remove_employee_and_regenerate"


class AIContextPointers(BaseModel):
    schedule_run_id: Optional[int] = None
    request_id: Optional[int] = None
    employee_id: Optional[str] = None
    pending_intent_token: Optional[str] = None


class AIChatRequest(BaseModel):
    message: str = Field(min_length=1)
    context: Optional[AIContextPointers] = None
    mode: str = Field(default="recommendation_only", pattern="^(recommendation_only|assistive)$")


class AIRecommendation(BaseModel):
    type: AIRecommendationType
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    fairness_impact: Optional[str] = None
    coverage_impact: Optional[str] = None
    constraint_rationale: Optional[str] = None
    suggested_params: Dict[str, Any] = Field(default_factory=dict)


class AIActionPayload(BaseModel):
    action_type: AIActionType
    label: str = Field(min_length=1)
    requires_confirmation: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)


class AIChatResponse(BaseModel):
    assistant_message: str
    recommendations: list[AIRecommendation] = Field(default_factory=list)
    action_payload: Optional[AIActionPayload] = None
    execution_mode: str = Field(default="recommendation_only", pattern="^(recommendation_only|assistive)$")
    new_schedule_run_id: Optional[int] = None
    error_code: Optional[str] = None
    follow_up_questions: list[str] = Field(default_factory=list)
    pending_intent_token: Optional[str] = None


class AIHealthResponse(BaseModel):
    ok: bool
    provider: str
    message: str
    error_code: Optional[str] = None


class AIActionExecuteRequest(BaseModel):
    action_payload: AIActionPayload


class AIActionExecuteResponse(BaseModel):
    status: str
    message: str
    executed_endpoint: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class AIDecisionFeedbackRequest(BaseModel):
    action_type: Optional[AIActionType] = None
    recommendation_type: Optional[AIRecommendationType] = None
    decision: str = Field(pattern="^(rejected|suggested)$")
    schedule_run_id: Optional[int] = None


class AIKpiResponse(BaseModel):
    period_days: int
    suggestions: int
    confirmed_actions: int
    fairness_delta_avg: float
    request_acceptance_rate_percent: float
    conflict_resolution_success_rate_percent: float
