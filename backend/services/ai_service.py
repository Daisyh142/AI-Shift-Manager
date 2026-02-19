from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from ..config import get_settings
from ..models import AIDecisionLog, Assignment, ScheduleRun, Shift, TimeOffRequest
from ..schemas import (
    AIActionExecuteRequest,
    AIActionExecuteResponse,
    AIActionPayload,
    AIActionType,
    AIChatRequest,
    AIChatResponse,
    AIDecisionFeedbackRequest,
    AIKpiResponse,
    AIRecommendation,
    AIRecommendationType,
    TimeOffStatus,
)
from ..services.scheduling_service import generate_and_persist_schedule


@dataclass(frozen=True)
class ScheduleContext:
    schedule_run_id: int | None
    fairness_percent: float
    coverage_percent: float
    violations: list[str]
    mode: str | None
    status: str | None
    pending_requests_count: int


def _latest_schedule_run(session: Session) -> ScheduleRun | None:
    """Returns the most recent draft run, falling back to the latest published run."""
    draft = session.exec(
        select(ScheduleRun).where(ScheduleRun.status == "draft").order_by(ScheduleRun.created_at.desc())
    ).first()
    if draft:
        return draft
    return session.exec(
        select(ScheduleRun).where(ScheduleRun.status == "published").order_by(ScheduleRun.created_at.desc())
    ).first()


def _coverage_percent_for_run(session: Session, run: ScheduleRun) -> float:
    """Calculates the percentage of shifts that are fully staffed for a given run."""
    period_start = run.week_start_date
    period_end = period_start + timedelta(days=13)
    shifts = session.exec(
        select(Shift).where(Shift.date >= period_start, Shift.date <= period_end)
    ).all()
    if not shifts:
        return 100.0
    assignments = session.exec(
        select(Assignment).where(Assignment.schedule_run_id == run.id)
    ).all()
    assigned_counts: dict[str, int] = {}
    for row in assignments:
        assigned_counts[row.shift_id] = assigned_counts.get(row.shift_id, 0) + 1
    understaffed = 0
    for shift in shifts:
        if assigned_counts.get(shift.id, 0) < shift.required_staff:
            understaffed += 1
    return round(100.0 * (len(shifts) - understaffed) / len(shifts), 2)


def _build_context(session: Session, request: AIChatRequest) -> ScheduleContext:
    """Assembles live schedule metrics into a ScheduleContext for the AI prompt."""
    run: ScheduleRun | None = None
    if request.context and request.context.schedule_run_id:
        run = session.get(ScheduleRun, request.context.schedule_run_id)
    if not run:
        run = _latest_schedule_run(session)

    pending_requests_count = len(
        session.exec(
            select(TimeOffRequest).where(TimeOffRequest.status == TimeOffStatus.PENDING.value)
        ).all()
    )
    if not run:
        return ScheduleContext(
            schedule_run_id=None,
            fairness_percent=0.0,
            coverage_percent=0.0,
            violations=[],
            mode=None,
            status=None,
            pending_requests_count=pending_requests_count,
        )

    try:
        violations = json.loads(run.violations_json)
    except json.JSONDecodeError:
        violations = []
    return ScheduleContext(
        schedule_run_id=run.id,
        fairness_percent=round(float(run.overall_score or 0.0), 2),
        coverage_percent=_coverage_percent_for_run(session, run),
        violations=violations,
        mode=run.mode,
        status=run.status,
        pending_requests_count=pending_requests_count,
    )


def _fallback_message(context: ScheduleContext, user_message: str) -> str:
    """Returns a deterministic assistant message when Gemini is unavailable."""
    if context.schedule_run_id is None:
        return (
            "I cannot see a generated schedule yet. Generate and review a schedule first, "
            "then ask me to explain fairness or coverage trade-offs."
        )
    return (
        f"For run #{context.schedule_run_id}, fairness is {context.fairness_percent:.1f}% and "
        f"coverage is {context.coverage_percent:.1f}%. "
        f"There are {len(context.violations)} validation violations and "
        f"{context.pending_requests_count} pending request(s). "
        f"Based on your prompt ('{user_message}'), I recommend focusing first on fairness gaps, "
        "then re-running with a precise regenerate reason if needed."
    )


def _gemini_message(user_message: str, context: ScheduleContext) -> str:
    """Calls Gemini via LangChain with schedule context; falls back to a deterministic reply on any error."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return _fallback_message(context, user_message)
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return _fallback_message(context, user_message)

    model = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        timeout=settings.ai_timeout_seconds,
        temperature=0.2,
    )
    system = (
        "You are an assistant for a deterministic shift scheduler. "
        "Do not invent data. Keep the answer concise and operational for an owner. "
        "Mention fairness impact, coverage impact, and policy constraints."
    )
    context_blob = (
        f"schedule_run_id={context.schedule_run_id}, fairness={context.fairness_percent}, "
        f"coverage={context.coverage_percent}, violations={context.violations[:6]}, "
        f"pending_requests={context.pending_requests_count}, mode={context.mode}, status={context.status}"
    )
    human = (
        f"Owner question: {user_message}\n"
        f"Deterministic context: {context_blob}\n"
        "Respond in 4-6 sentences."
    )
    try:
        response = model.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        text = getattr(response, "content", "")
        if isinstance(text, list):
            text = " ".join(str(item) for item in text)
        return str(text).strip() or _fallback_message(context, user_message)
    except Exception:
        return _fallback_message(context, user_message)


def generate_chat_response(session: Session, owner_user_id: int, request: AIChatRequest) -> AIChatResponse:
    """Builds an AI chat response with recommendations and an optional owner-confirmable action."""
    settings = get_settings()
    context = _build_context(session, request)
    assistant_message = _gemini_message(request.message, context)

    recommendation = AIRecommendation(
        type=AIRecommendationType.EXPLAIN_SCHEDULE_FAIRNESS,
        title="Fairness explanation",
        rationale=assistant_message,
        confidence=0.86 if context.schedule_run_id else 0.55,
        fairness_impact=(
            "Expected to improve fairness if regeneration focuses on under-served employees."
            if context.fairness_percent < 70
            else "Fairness is already strong; prioritize preserving current distribution."
        ),
        coverage_impact=(
            "Coverage risk is moderate; validate understaffed shifts before approving more time off."
            if context.coverage_percent < 90
            else "Coverage is currently healthy."
        ),
        constraint_rationale="All actions must flow through existing scheduler and policy constraints.",
        suggested_params={
            "schedule_run_id": context.schedule_run_id,
            "target_fairness_floor": 70,
        },
    )

    action_payload: AIActionPayload | None = None
    if context.schedule_run_id and context.fairness_percent < 65:
        action_payload = AIActionPayload(
            action_type=AIActionType.REDO_SCHEDULE,
            label="Regenerate schedule with fairness focus",
            requires_confirmation=True,
            params={
                "schedule_run_id": context.schedule_run_id,
                "reason": "Improve fairness for under-assigned employees while maintaining coverage.",
            },
        )

    execution_mode = "recommendation_only"
    if request.mode == "assistive" and settings.ai_allow_assistive_mode:
        execution_mode = "assistive"

    if context.schedule_run_id:
        run = session.get(ScheduleRun, context.schedule_run_id)
        if run and not run.explanation_text:
            run.explanation_text = assistant_message[:4000]
            session.add(run)
            session.commit()

    session.add(
        AIDecisionLog(
            owner_user_id=owner_user_id,
            message=request.message,
            recommendation_type=AIRecommendationType.EXPLAIN_SCHEDULE_FAIRNESS.value,
            action_type=action_payload.action_type.value if action_payload else None,
            owner_decision="suggested",
            schedule_run_id=context.schedule_run_id,
            fairness_before=context.fairness_percent if context.schedule_run_id else None,
            fairness_after=None,
            outcome_json=json.dumps(
                {
                    "coverage_percent": context.coverage_percent,
                    "violations_count": len(context.violations),
                    "pending_requests_count": context.pending_requests_count,
                }
            ),
        )
    )
    session.commit()

    return AIChatResponse(
        assistant_message=assistant_message,
        recommendations=[recommendation],
        action_payload=action_payload,
        execution_mode=execution_mode,
    )


def execute_confirmed_action(
    session: Session,
    owner_user_id: int,
    request: AIActionExecuteRequest,
) -> AIActionExecuteResponse:
    """Runs an owner-approved AI action through existing deterministic endpoints."""
    action = request.action_payload
    result: dict[str, Any] | None = None
    endpoint: str | None = None

    if action.action_type == AIActionType.REDO_SCHEDULE:
        schedule_run_id = int(action.params.get("schedule_run_id"))
        reason = str(action.params.get("reason", "Owner confirmed AI regeneration.")).strip()
        prev = session.get(ScheduleRun, schedule_run_id)
        if not prev:
            return AIActionExecuteResponse(
                status="error",
                message="schedule_run_not_found",
            )
        before = float(prev.overall_score or 0.0)
        new_run = generate_and_persist_schedule(
            session=session,
            week_start_date=prev.week_start_date,
            mode=prev.mode,
            redo_of_schedule_run_id=prev.id,
            redo_reason=reason,
        )
        after = float(new_run.overall_score or 0.0)
        result = {"new_schedule_run_id": new_run.id, "fairness_before": before, "fairness_after": after}
        endpoint = f"/schedules/{schedule_run_id}/redo"
    elif action.action_type == AIActionType.APPROVE_TIME_OFF:
        from ..routers.time_off import approve_time_off

        request_id = int(action.params.get("request_id"))
        response = approve_time_off(request_id=request_id, _owner=None, session=session)
        result = response.model_dump()
        endpoint = f"/time-off/requests/{request_id}/approve"
    elif action.action_type == AIActionType.DENY_TIME_OFF:
        from ..routers.time_off import deny_time_off

        request_id = int(action.params.get("request_id"))
        response = deny_time_off(request_id=request_id, _owner=None, session=session)
        result = response.model_dump()
        endpoint = f"/time-off/requests/{request_id}/deny"
    else:
        return AIActionExecuteResponse(
            status="error",
            message="unsupported_action_type",
        )

    session.add(
        AIDecisionLog(
            owner_user_id=owner_user_id,
            message="owner_confirmed_ai_action",
            recommendation_type=None,
            action_type=action.action_type.value,
            owner_decision="confirmed",
            schedule_run_id=int(action.params.get("schedule_run_id")) if action.params.get("schedule_run_id") else None,
            fairness_before=result.get("fairness_before") if result else None,
            fairness_after=result.get("fairness_after") if result else None,
            outcome_json=json.dumps(result or {}),
        )
    )
    session.commit()
    return AIActionExecuteResponse(
        status="ok",
        message="action_executed",
        executed_endpoint=endpoint,
        result=result,
    )


def log_decision_feedback(session: Session, owner_user_id: int, request: AIDecisionFeedbackRequest) -> None:
    """Persists an owner accept/reject decision on an AI suggestion for KPI tracking."""
    session.add(
        AIDecisionLog(
            owner_user_id=owner_user_id,
            message="owner_feedback",
            recommendation_type=request.recommendation_type.value if request.recommendation_type else None,
            action_type=request.action_type.value if request.action_type else None,
            owner_decision=request.decision,
            schedule_run_id=request.schedule_run_id,
            outcome_json="{}",
        )
    )
    session.commit()


def get_ai_kpis(session: Session, days: int) -> AIKpiResponse:
    """Aggregates AI decision logs into usage and impact metrics over the given period."""
    period_days = max(1, days)
    cutoff = datetime.utcnow() - timedelta(days=period_days)
    rows = session.exec(
        select(AIDecisionLog).where(AIDecisionLog.created_at >= cutoff)
    ).all()

    suggestions = len([r for r in rows if r.owner_decision in {"suggested", "rejected", "confirmed"}])
    confirmed = [r for r in rows if r.owner_decision == "confirmed"]
    confirmed_actions = len(confirmed)

    deltas = [
        (r.fairness_after - r.fairness_before)
        for r in confirmed
        if r.fairness_after is not None and r.fairness_before is not None
    ]
    fairness_delta_avg = round(sum(deltas) / len(deltas), 2) if deltas else 0.0

    request_actions = [r for r in confirmed if r.action_type in {"approve_time_off", "deny_time_off"}]
    request_acceptance_rate = (
        100.0
        * len([r for r in request_actions if r.action_type == "approve_time_off"])
        / len(request_actions)
        if request_actions
        else 0.0
    )

    conflict_actions = [r for r in confirmed if r.action_type == "redo_schedule"]
    conflict_resolution_success = (
        100.0
        * len([r for r in conflict_actions if (r.fairness_after or 0) > (r.fairness_before or 0)])
        / len(conflict_actions)
        if conflict_actions
        else 0.0
    )

    return AIKpiResponse(
        period_days=period_days,
        suggestions=suggestions,
        confirmed_actions=confirmed_actions,
        fairness_delta_avg=fairness_delta_avg,
        request_acceptance_rate_percent=round(request_acceptance_rate, 2),
        conflict_resolution_success_rate_percent=round(conflict_resolution_success, 2),
    )
