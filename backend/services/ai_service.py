from __future__ import annotations

import json
import logging
import os
import re
import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from ..config import get_settings
from ..models import AIDecisionLog, Assignment, Employee, ScheduleRun, Shift, TimeOffRequest
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
    ScheduleChangeConstraints,
    ScheduleChangeRequest,
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
    employee_summary: str = ""


@dataclass(frozen=True)
class ParsedControlIntent:
    recognized: bool
    follow_up_questions: list[str]
    pending_intent_token: str | None
    change_request: ScheduleChangeRequest | None


def _latest_schedule_run(session: Session) -> ScheduleRun | None:
    draft = session.exec(
        select(ScheduleRun).where(ScheduleRun.status == "draft").order_by(ScheduleRun.created_at.desc())
    ).first()
    if draft:
        return draft
    return session.exec(
        select(ScheduleRun).where(ScheduleRun.status == "published").order_by(ScheduleRun.created_at.desc())
    ).first()


def _coverage_percent_for_run(session: Session, run: ScheduleRun) -> float:
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
        employees = session.exec(select(Employee)).all()
        employee_summary = ", ".join(f"{e.id}: {e.name}" for e in employees) if employees else ""
        return ScheduleContext(
            schedule_run_id=None,
            fairness_percent=0.0,
            coverage_percent=0.0,
            violations=[],
            mode=None,
            status=None,
            pending_requests_count=pending_requests_count,
            employee_summary=employee_summary,
        )

    try:
        violations = json.loads(run.violations_json)
    except json.JSONDecodeError:
        print("[ai_service] Failed to parse run.violations_json; defaulting to empty violations list.")
        violations = []
    employees = session.exec(select(Employee)).all()
    employee_summary = ", ".join(f"{e.id}: {e.name}" for e in employees) if employees else ""
    return ScheduleContext(
        schedule_run_id=run.id,
        fairness_percent=round(float(run.overall_score or 0.0), 2),
        coverage_percent=_coverage_percent_for_run(session, run),
        violations=violations,
        mode=run.mode,
        status=run.status,
        pending_requests_count=pending_requests_count,
        employee_summary=employee_summary,
    )


def _resolve_period_start_from_message(message: str, base_period_start: date) -> date | None:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", message)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    lowered = message.lower()
    if "next" in lowered:
        return base_period_start + timedelta(days=14)
    if "current" in lowered or "this pay period" in lowered or "this period" in lowered:
        return base_period_start
    return None


def _parse_delta_hours(message: str) -> float | None:
    lowered = message.lower()
    sign = 1.0
    if any(token in lowered for token in ["fewer", "less", "reduce", "cut"]):
        sign = -1.0
    number_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*hours?", lowered)
    if number_match:
        return sign * float(number_match.group(1).lstrip("+"))
    naked_match = re.search(r"\b([+-]?\d+(?:\.\d+)?)\b", lowered)
    if naked_match and "hour" in lowered:
        return sign * float(naked_match.group(1).lstrip("+"))
    return None


def _extract_constraints_from_message(message: str) -> ScheduleChangeConstraints:
    lowered = message.lower()
    max_days_per_week = None
    max_days_match = re.search(r"(?:max\s*(\d)\s*days|(\d)\s*days?\s*(?:max|per week|/week))", lowered)
    if max_days_match:
        max_days_per_week = int(max_days_match.group(1) or max_days_match.group(2))
    prefer_shift_ranges: list[str] = []
    avoid_shift_ranges: list[str] = []
    for start, end in re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", message):
        normalized = f"{start.zfill(5)}-{end.zfill(5)}"
        if "avoid" in lowered:
            avoid_shift_ranges.append(normalized)
        else:
            prefer_shift_ranges.append(normalized)
    if "avoid closing" in lowered:
        avoid_shift_ranges.append("16:00-23:00")
    return ScheduleChangeConstraints(
        prefer_shift_ranges=sorted(set(prefer_shift_ranges)),
        avoid_shift_ranges=sorted(set(avoid_shift_ranges)),
        max_days_per_week=max_days_per_week,
    )


def _find_employee_id_for_message(session: Session, message: str) -> str | None:
    lowered = message.lower()
    employees = session.exec(select(Employee)).all()
    for employee in employees:
        if employee.id.lower() in lowered:
            return employee.id
    for employee in employees:
        name_parts = [part for part in re.split(r"\W+", employee.name.lower()) if part]
        if any(len(part) >= 3 and part in lowered for part in name_parts):
            return employee.id
    return None


def _encode_pending_intent(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_pending_intent(token: str) -> dict[str, Any] | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8"))
        value = json.loads(decoded.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _default_period_start(session: Session, request: AIChatRequest | None = None) -> date:
    if request and request.context and request.context.schedule_run_id:
        pointed_run = session.get(ScheduleRun, request.context.schedule_run_id)
        if pointed_run:
            return pointed_run.week_start_date
    base_run = _latest_schedule_run(session)
    return base_run.week_start_date if base_run else date.today() - timedelta(days=date.today().weekday())


def _is_fairness_target_request(message: str) -> bool:
    lowered = message.lower()
    return "fairness" in lowered or ("%" in lowered and ("give" in lowered or "set" in lowered))


def _is_hours_adjust_request(message: str) -> bool:
    lowered = message.lower()
    return ("hour" in lowered or "shift" in lowered) and any(
        token in lowered for token in ["more", "less", "fewer", "reduce", "add", "increase", "decrease", "give"]
    )


def _parse_confirmation(message: str) -> bool | None:
    lowered = message.lower()
    if any(token in lowered for token in ["confirm", "yes", "yep", "correct", "agreed"]):
        return True
    if any(token in lowered for token in ["no", "don't", "do not"]):
        return False
    return None


def _parse_exactness_strict(message: str) -> bool | None:
    lowered = message.lower()
    if "as close as possible" in lowered or "best effort" in lowered:
        return False
    if "exact" in lowered or "strict" in lowered:
        return True
    return None


def _parse_tradeoff_policy(message: str) -> str | None:
    lowered = message.lower()
    if "lowest priority" in lowered or "low priority" in lowered:
        return "LOWEST_PRIORITY_LOSES_FIRST"
    if "do not reduce managers" in lowered or "protect managers" in lowered:
        return "PROTECT_MANAGERS"
    return None


def _parse_target_utilization(message: str) -> float | None:
    lowered = message.lower()
    if any(
        phrase in lowered
        for phrase in [
            "100 fairness",
            "100% fairness",
            "100 fairness score",
            "100% fairness score",
            "100 utilization",
            "100% utilization",
            "full utilization",
            "full max hours",
            "max hours",
            "full hours",
        ]
    ):
        return 1.0
    percent_match = re.search(r"\b(\d{1,3})(?:\s*%)?\s*(?:fairness|utilization)\b", lowered)
    if percent_match:
        return max(0.0, min(1.0, float(percent_match.group(1)) / 100.0))
    return None


def _parse_exactness(message: str) -> str | None:
    parsed = _parse_exactness_strict(message)
    if parsed is True:
        return "STRICT"
    if parsed is False:
        return "AS_CLOSE_AS_POSSIBLE"
    return None


def _is_dev_slot_logging_enabled() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"dev", "development", "local", "test"}


def _slot_log(stage: str, payload: dict[str, Any]) -> None:
    if not _is_dev_slot_logging_enabled():
        return
    try:
        logger.info("ai_chat_slot_filling %s %s", stage, json.dumps(payload, default=str, sort_keys=True))
    except Exception:
        logger.info("ai_chat_slot_filling %s %r", stage, payload)


def _employee_name_for_id(session: Session, employee_id: str | None) -> str | None:
    if not employee_id:
        return None
    employee = session.get(Employee, employee_id)
    return employee.name if employee else None


def _merge_constraints(
    existing: ScheduleChangeConstraints,
    parsed: ScheduleChangeConstraints,
) -> ScheduleChangeConstraints:
    if parsed.max_days_per_week is not None:
        existing.max_days_per_week = parsed.max_days_per_week
    existing.avoid_shift_ranges = sorted(set(existing.avoid_shift_ranges + parsed.avoid_shift_ranges))
    existing.prefer_shift_ranges = sorted(set(existing.prefer_shift_ranges + parsed.prefer_shift_ranges))
    return existing


def _apply_default_constraints(constraints: ScheduleChangeConstraints) -> ScheduleChangeConstraints:
    if constraints.max_days_per_week is None:
        constraints.max_days_per_week = 5
    return constraints


def _build_pending_intent_payload(
    *,
    intent_type: str,
    employee_id: str | None,
    employee_name: str | None,
    period_start: str | None,
    target_utilization: float | None = None,
    exactness: str | None = None,
    tradeoff_policy: str | None = None,
    delta_hours: float | None = None,
    constraints: ScheduleChangeConstraints | None = None,
    reason: str | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "intent_type": intent_type,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "period_start": period_start,
        "target_utilization": target_utilization,
        "exactness": exactness,
        "tradeoff_policy": tradeoff_policy,
        "delta_hours": delta_hours,
        "constraints": (constraints or ScheduleChangeConstraints()).model_dump(),
        "reason": reason or "Owner request via chat",
        "missing_fields": missing_fields or [],
    }


def _describe_missing_utilization_target(employee_name: str | None) -> str:
    if employee_name:
        return f"Do you want {employee_name} at full utilization, or just increased hours?"
    return "Do you want full utilization, or just increased hours?"


def _confirmation_message(
    *,
    session: Session,
    request: AIChatRequest,
    change_request: ScheduleChangeRequest,
) -> str:
    employee_name = _employee_name_for_id(session, change_request.employee_id) or change_request.employee_id
    base_period_start = _default_period_start(session, request)
    period_label = (
        "the current pay period"
        if change_request.period_start == base_period_start
        else f"the pay period starting {change_request.period_start.isoformat()}"
    )
    max_days = change_request.constraints.max_days_per_week
    if change_request.type == "SET_UTILIZATION_TARGET":
        target_label = (
            "full utilization"
            if (change_request.target_utilization or 0.0) >= 0.999
            else f"{(change_request.target_utilization or 0.0):.0%} utilization"
        )
        exactness_label = "strictly" if change_request.strict else "as closely as possible"
        tradeoff_label = (
            "lowest-priority employees losing hours first"
            if change_request.tradeoff_policy == "LOWEST_PRIORITY_LOSES_FIRST"
            else change_request.tradeoff_policy.replace("_", " ").lower()
        )
        max_days_label = f"max {max_days} days/week preserved" if max_days is not None else "existing constraints preserved"
        return (
            f"Got it. I'm adjusting {employee_name}'s schedule for {period_label}, targeting {target_label} "
            f"{exactness_label}, with {tradeoff_label} and {max_days_label}."
        )
    direction = "increasing" if (change_request.delta_hours or 0.0) >= 0 else "reducing"
    delta_hours = abs(change_request.delta_hours or 0.0)
    max_days_label = f" Max {max_days} days/week will stay in place." if max_days is not None else ""
    return (
        f"Got it. I'm {direction} {employee_name}'s hours by {delta_hours:g} for {period_label}."
        f"{max_days_label}"
    )


def _complete_intent_from_token(
    *,
    session: Session,
    request: AIChatRequest,
    token_payload: dict[str, Any],
) -> ParsedControlIntent:
    message = request.message.strip()
    base_period_start = _default_period_start(session, request)
    intent_type = str(token_payload.get("intent_type", ""))
    _slot_log("pending_intent_before_merge", token_payload)
    employee_id = token_payload.get("employee_id") or _find_employee_id_for_message(session, message)
    employee_name = token_payload.get("employee_name") or _employee_name_for_id(session, employee_id)
    period_start = token_payload.get("period_start")
    parsed_period = _resolve_period_start_from_message(message, base_period_start)
    if parsed_period is not None:
        period_start = parsed_period.isoformat()
    constraints = ScheduleChangeConstraints.model_validate(token_payload.get("constraints", {}))
    parsed_constraints = _extract_constraints_from_message(message)
    constraints = _merge_constraints(constraints, parsed_constraints)
    parsed_fields: dict[str, Any] = {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "period_start": period_start,
        "constraints": parsed_constraints.model_dump(),
    }
    if period_start is None:
        period_start = base_period_start.isoformat()

    if intent_type == "SET_UTILIZATION_TARGET":
        target_utilization = token_payload.get("target_utilization")
        parsed_target_utilization = _parse_target_utilization(message)
        if parsed_target_utilization is not None:
            target_utilization = parsed_target_utilization
        exactness = token_payload.get("exactness")
        if exactness is None and token_payload.get("strict") is not None:
            exactness = "STRICT" if bool(token_payload.get("strict")) else "AS_CLOSE_AS_POSSIBLE"
        parsed_exactness = _parse_exactness(message)
        if parsed_exactness is not None:
            exactness = parsed_exactness
        if exactness is None:
            exactness = "AS_CLOSE_AS_POSSIBLE"
        tradeoff_policy = token_payload.get("tradeoff_policy")
        parsed_tradeoff = _parse_tradeoff_policy(message)
        if parsed_tradeoff is not None:
            tradeoff_policy = parsed_tradeoff
        if not tradeoff_policy:
            tradeoff_policy = "LOWEST_PRIORITY_LOSES_FIRST"
        constraints = _apply_default_constraints(constraints)
        parsed_fields.update(
            {
                "target_utilization": target_utilization,
                "exactness": exactness,
                "tradeoff_policy": tradeoff_policy,
            }
        )
        _slot_log("parsed_fields_from_latest_message", parsed_fields)
        missing: list[str] = []
        followups: list[str] = []
        if employee_id is None:
            missing.append("employee_id")
            followups.append("Which employee should I target?")
        if target_utilization is None:
            missing.append("target_utilization")
            followups.append(_describe_missing_utilization_target(employee_name))
        merged_payload = _build_pending_intent_payload(
            intent_type=intent_type,
            employee_id=employee_id,
            employee_name=employee_name,
            period_start=period_start,
            target_utilization=float(target_utilization) if target_utilization is not None else None,
            exactness=exactness,
            tradeoff_policy=tradeoff_policy,
            constraints=constraints,
            reason=str(token_payload.get("reason") or "Owner request via chat"),
            missing_fields=missing,
        )
        _slot_log("pending_intent_after_merge", merged_payload)
        _slot_log(
            "pending_intent_decision",
            {"missing_fields": missing, "execution_triggered": not missing},
        )
        if missing:
            return ParsedControlIntent(
                recognized=True,
                follow_up_questions=followups,
                pending_intent_token=_encode_pending_intent(merged_payload),
                change_request=None,
            )
        change_request = ScheduleChangeRequest(
            type="SET_UTILIZATION_TARGET",
            employee_id=str(employee_id),
            period_start=date.fromisoformat(str(period_start)),
            target_utilization=float(target_utilization),
            strict=exactness == "STRICT",
            tradeoff_policy=str(tradeoff_policy),
            constraints=constraints,
            reason=str(token_payload.get("reason") or "Owner request via chat"),
        )
        return ParsedControlIntent(recognized=True, follow_up_questions=[], pending_intent_token=None, change_request=change_request)

    delta_hours = token_payload.get("delta_hours")
    parsed_delta = _parse_delta_hours(message)
    if parsed_delta is not None:
        delta_hours = parsed_delta
    constraints = _apply_default_constraints(constraints)
    parsed_fields.update({"delta_hours": delta_hours})
    _slot_log("parsed_fields_from_latest_message", parsed_fields)
    missing: list[str] = []
    followups: list[str] = []
    if employee_id is None:
        missing.append("employee_id")
        followups.append("Which employee should I adjust?")
    if delta_hours is None:
        missing.append("delta_hours")
        followups.append("How many more or fewer hours should I target over the 2-week period?")
    merged_payload = _build_pending_intent_payload(
        intent_type="ADJUST_HOURS",
        employee_id=employee_id,
        employee_name=employee_name,
        period_start=period_start,
        delta_hours=float(delta_hours) if delta_hours is not None else None,
        constraints=constraints,
        reason=str(token_payload.get("reason") or "Owner request via chat"),
        missing_fields=missing,
    )
    _slot_log("pending_intent_after_merge", merged_payload)
    _slot_log(
        "pending_intent_decision",
        {"missing_fields": missing, "execution_triggered": not missing},
    )
    if followups:
        return ParsedControlIntent(
            recognized=True,
            follow_up_questions=followups,
            pending_intent_token=_encode_pending_intent(merged_payload),
            change_request=None,
        )
    change_request = ScheduleChangeRequest(
        type="ADJUST_HOURS",
        employee_id=str(employee_id),
        period_start=date.fromisoformat(str(period_start)),
        delta_hours=float(delta_hours),
        constraints=constraints,
        reason=str(token_payload.get("reason") or "Owner request via chat"),
    )
    return ParsedControlIntent(recognized=True, follow_up_questions=[], pending_intent_token=None, change_request=change_request)


def _maybe_parse_control_intent(
    *,
    session: Session,
    request: AIChatRequest,
) -> ParsedControlIntent:
    token = request.context.pending_intent_token if request.context else None
    if token:
        payload = _decode_pending_intent(token)
        if payload:
            return _complete_intent_from_token(session=session, request=request, token_payload=payload)
    message = request.message.strip()
    base_period_start = _default_period_start(session, request)
    if _is_fairness_target_request(message):
        employee_id = _find_employee_id_for_message(session, message)
        parsed_period = _resolve_period_start_from_message(message, base_period_start)
        payload = _build_pending_intent_payload(
            intent_type="SET_UTILIZATION_TARGET",
            employee_id=employee_id,
            employee_name=_employee_name_for_id(session, employee_id),
            period_start=parsed_period.isoformat() if parsed_period else base_period_start.isoformat(),
            target_utilization=_parse_target_utilization(message),
            exactness=_parse_exactness(message),
            tradeoff_policy=_parse_tradeoff_policy(message),
            constraints=_extract_constraints_from_message(message),
            missing_fields=[],
        )
        return _complete_intent_from_token(session=session, request=request, token_payload=payload)
    if _is_hours_adjust_request(message):
        employee_id = _find_employee_id_for_message(session, message)
        parsed_period = _resolve_period_start_from_message(message, base_period_start)
        payload = _build_pending_intent_payload(
            intent_type="ADJUST_HOURS",
            employee_id=employee_id,
            employee_name=_employee_name_for_id(session, employee_id),
            period_start=parsed_period.isoformat() if parsed_period else base_period_start.isoformat(),
            delta_hours=_parse_delta_hours(message),
            constraints=_extract_constraints_from_message(message),
            missing_fields=[],
        )
        return _complete_intent_from_token(session=session, request=request, token_payload=payload)
    return ParsedControlIntent(recognized=False, follow_up_questions=[], pending_intent_token=None, change_request=None)


def _fallback_message(context: ScheduleContext, user_message: str, reason: str = "") -> str:
    if reason:
        logger.warning("AI chat fallback: %s", reason)
    if context.schedule_run_id is None:
        return "I don't have a schedule to look at yet. Generate one first, then ask me to adjust it or explain trade-offs."
    return (
        "The AI assistant isn't available right now. "
        "Once the AI is connected, you can ask in plain language (e.g. 'give Riley fewer hours') and I'll regenerate the schedule."
    )


def _categorize_ai_error(reason: str) -> str:
    normalized = reason.lower()
    if "missing" in normalized and "api_key" in normalized:
        return "missing_api_key"
    if "unauthorized" in normalized or "401" in normalized:
        return "unauthorized"
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout"
    return "server_error"


def get_ai_health() -> tuple[bool, str, str | None, str]:
    settings = get_settings()
    provider = "gemini"
    if not settings.gemini_api_key:
        return (False, provider, "missing_api_key", "AI unavailable (missing API key)")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI health import failed: %r", exc)
        print(f"[ai_service] AI health import failed: {exc!r}")
        return (False, provider, "server_error", "AI unavailable (server error)")

    try:
        model = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            timeout=max(10, settings.ai_timeout_seconds),
            temperature=0.0,
        )
        model.invoke([HumanMessage(content="ping")])
        return (True, provider, None, "AI provider reachable")
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI health probe failed: %r", exc)
        print(f"[ai_service] AI health probe failed: {exc!r}")
        code = _categorize_ai_error(str(exc))
        if code == "unauthorized":
            return (False, provider, code, "AI unavailable (401 unauthorized)")
        if code == "timeout":
            return (False, provider, code, "AI unavailable (timeout)")
        return (False, provider, code, "AI unavailable (server error)")


def _parse_regenerate_line(text: str) -> tuple[str, str | None]:
    if "REGENERATE:" not in text:
        return (text, None)
    lines = text.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line.upper().startswith("REGENERATE:"):
            reason = line[len("REGENERATE:") :].strip()
            if reason:
                without = "\n".join(lines[:i] + lines[i + 1 :]).strip()
                return (without, reason)
            break
    return (text, None)


def _gemini_message(
    user_message: str,
    context: ScheduleContext,
    session: Session,
) -> tuple[str, str | None]:
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.error("AI chat unavailable: missing_api_key")
        return (_fallback_message(context, user_message, reason="missing_api_key"), "missing api key")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
        from .agent_tools import make_schedule_tools
    except Exception as e:  # noqa: BLE001
        logger.exception("AI chat import failed: %r", e)
        return (_fallback_message(context, user_message, reason=f"import error: {e!r}"), "server_error")

    tools = make_schedule_tools(session)
    model = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        timeout=settings.ai_timeout_seconds,
        temperature=0.2,
    ).bind_tools(tools)

    system = (
        "You are a real, conversational assistant for the owner of a small business who manages shift schedules. "
        "You have four tools: get_employee_data, generate_draft_schedule, override_constraint, get_metrics. "
        "Use them to answer questions and make changes — do not guess at employee ids or schedule data.\n\n"
        "Hard rules you must follow:\n"
        "- The owner is ONLY scheduled as a last resort when zero eligible employees can cover a shift.\n"
        "- Every working day must have at least 1 cook, 1 server, 1 busser, and 1 manager or shift lead.\n"
        "- A shift lead or manager must always be scheduled alongside regular employees.\n"
        "- Never approve a time-off request on your own. Ask the owner to confirm first, then call override_constraint.\n\n"
        "When the owner asks for a schedule change:\n"
        "1) Use get_employee_data to look up any employees mentioned by name — resolve names to ids first.\n"
        "2) Double-check the request makes sense given their role and current hours. For example, if a shift lead "
        "already has the fewest hours, that is worth mentioning before making the change.\n"
        "3) Call generate_draft_schedule to create the new schedule.\n"
        "4) Call get_metrics on the resulting run_id to verify the schedule meets all hard constraints.\n"
        "5) If there are hard violations (missing category, missing leadership, etc.), explain them and ask how "
        "the owner wants to resolve them — do NOT silently accept a broken schedule.\n"
        "6) Reply conversationally — no boilerplate. Mention trade-offs if coverage will be affected.\n\n"
        "When the owner is only asking a question (no change needed), answer directly without calling any tools unless "
        "you need live data to answer accurately.\n\n"
        "Clarification rule: if the owner's intent is ambiguous, ask AT MOST ONE clarifying question and then proceed "
        "with the most reasonable interpretation. Do NOT list multiple follow-up questions. Do NOT ask the same "
        "thing twice. A single concise confirmation is enough — for example: "
        "'Got it — give Sky more hours this week. She currently has the fewest hours on the team despite being a "
        "shift lead, so this makes sense. Want me to regenerate with her hours bumped up?'"
    )
    context_blob = (
        f"Current run #{context.schedule_run_id}: fairness {context.fairness_percent:.0f}%, "
        f"coverage {context.coverage_percent:.0f}%, {len(context.violations)} violations, "
        f"{context.pending_requests_count} pending requests. "
        f"Employees (id: name): {context.employee_summary}"
    )
    human = f"Owner: {user_message}\n\nSchedule context: {context_blob}"

    messages: list = [SystemMessage(content=system), HumanMessage(content=human)]

    try:
        MAX_TOOL_ITERATIONS = 6
        for _ in range(MAX_TOOL_ITERATIONS):
            response = model.invoke(messages)
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                break

            for call in tool_calls:
                matching = next((t for t in tools if t.name == call["name"]), None)
                if matching:
                    tool_result = matching.invoke(call["args"])
                    messages.append(
                        ToolMessage(content=str(tool_result), tool_call_id=call["id"])
                    )
                else:
                    tool_name = call["name"]
                    messages.append(
                        ToolMessage(
                            content=f'{{"error": "unknown tool: {tool_name}"}}',
                            tool_call_id=call["id"],
                        )
                    )

        final_text = str(getattr(messages[-1], "content", "")).strip()
        if isinstance(messages[-1].content, list):
            final_text = " ".join(str(p) for p in messages[-1].content).strip()

        if final_text:
            return (final_text, None)
        return (_fallback_message(context, user_message, reason="empty response"), "server_error")

    except Exception as e:  # noqa: BLE001
        logger.exception("AI chat request failed: %r", e)
        code = _categorize_ai_error(str(e))
        return (_fallback_message(context, user_message, reason=f"Gemini API error: {e!r}"), code)


def generate_chat_response(session: Session, owner_user_id: int, request: AIChatRequest) -> AIChatResponse:
    settings = get_settings()
    context = _build_context(session, request)
    parsed_intent = _maybe_parse_control_intent(session=session, request=request)
    if parsed_intent.recognized and parsed_intent.change_request is None:
        first_question = (
            parsed_intent.follow_up_questions[0]
            if parsed_intent.follow_up_questions
            else "Want me to go ahead and regenerate the schedule with that change?"
        )
        return AIChatResponse(
            assistant_message=f"Got it. {first_question}",
            recommendations=[],
            action_payload=None,
            execution_mode="recommendation_only",
            new_schedule_run_id=None,
            error_code=None,
            follow_up_questions=parsed_intent.follow_up_questions[:1],
            pending_intent_token=parsed_intent.pending_intent_token,
        )

    error_code: str | None = None
    assistant_message = ""
    if parsed_intent.change_request is not None:
        assistant_message = _confirmation_message(
            session=session,
            request=request,
            change_request=parsed_intent.change_request,
        )
    else:
        assistant_message, error_code = _gemini_message(request.message, context, session)

    new_schedule_run_id: int | None = None
    if parsed_intent.change_request is not None:
        base_run = _latest_schedule_run(session)
        if base_run is None:
            return AIChatResponse(
                assistant_message="Generate a schedule first, then ask me to adjust hours.",
                recommendations=[],
                action_payload=None,
                execution_mode="recommendation_only",
                new_schedule_run_id=None,
                error_code=None,
            )
        run_mode = base_run.mode
        redo_of_schedule_run_id = base_run.id if base_run.week_start_date == parsed_intent.change_request.period_start else None
        new_run = generate_and_persist_schedule(
            session=session,
            week_start_date=parsed_intent.change_request.period_start,
            mode=run_mode,
            redo_of_schedule_run_id=redo_of_schedule_run_id,
            redo_reason=parsed_intent.change_request.reason,
            schedule_change_request=parsed_intent.change_request,
        )
        new_schedule_run_id = new_run.id
        extra = ""
        if parsed_intent.change_request.type == "SET_UTILIZATION_TARGET":
            try:
                fairness_rows = json.loads(new_run.fairness_json)
            except json.JSONDecodeError:
                fairness_rows = []
            target_row = next(
                (row for row in fairness_rows if row.get("employee_id") == parsed_intent.change_request.employee_id),
                None,
            )
            achieved_util = float(target_row.get("utilization", 0.0)) if target_row else 0.0
            target_util = float(parsed_intent.change_request.target_utilization or 0.0)
            violations = json.loads(new_run.violations_json or "[]")
            infeasible_line = next((v for v in violations if v.startswith("infeasible_utilization_target:")), None)
            if infeasible_line:
                extra = (
                    f"\n\nResult: INFEASIBLE for strict target. Achieved utilization is {achieved_util:.2%} "
                    f"vs target {target_util:.2%}. Blocking constraint: {infeasible_line}."
                )
            else:
                extra = f"\n\nAchieved utilization for {parsed_intent.change_request.employee_id}: {achieved_util:.2%}."

        gemini_review = _ai_summarize_run(session=session, run_id=new_run.id)
        assistant_message = gemini_review + extra
    elif parsed_intent.change_request is None:
        latest_run = _latest_schedule_run(session)
        if latest_run and latest_run.id != context.schedule_run_id:
            new_schedule_run_id = latest_run.id

    execution_mode = "recommendation_only"
    if request.mode == "assistive" and settings.ai_allow_assistive_mode:
        execution_mode = "assistive"

    if context.schedule_run_id:
        run = session.get(ScheduleRun, context.schedule_run_id)
        if run and not run.explanation_text:
            run.explanation_text = assistant_message[:4000]
            session.add(run)
            session.commit()

    fairness_after: float | None = None
    if new_schedule_run_id is not None:
        maybe_new_run = session.get(ScheduleRun, new_schedule_run_id)
        fairness_after = float(maybe_new_run.overall_score or 0) if maybe_new_run else None

    session.add(
        AIDecisionLog(
            owner_user_id=owner_user_id,
            message=request.message,
            recommendation_type=AIRecommendationType.EXPLAIN_SCHEDULE_FAIRNESS.value,
            action_type=None,
            owner_decision="suggested",
            schedule_run_id=new_schedule_run_id or context.schedule_run_id,
            fairness_before=context.fairness_percent if context.schedule_run_id else None,
            fairness_after=fairness_after,
            outcome_json=json.dumps(
                {
                    "coverage_percent": context.coverage_percent,
                    "violations_count": len(context.violations),
                    "pending_requests_count": context.pending_requests_count,
                    "new_schedule_run_id": new_schedule_run_id,
                }
            ),
        )
    )
    session.commit()

    return AIChatResponse(
        assistant_message=assistant_message,
        recommendations=[],
        action_payload=None,
        execution_mode=execution_mode,
        new_schedule_run_id=new_schedule_run_id,
        error_code=error_code,
        follow_up_questions=[],
        pending_intent_token=None,
    )


def execute_confirmed_action(
    session: Session,
    owner_user_id: int,
    request: AIActionExecuteRequest,
) -> AIActionExecuteResponse:
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
    elif action.action_type == AIActionType.REMOVE_EMPLOYEE_AND_REGENERATE:
        from ..models import TimeOffRequest as DbTimeOffRequest
        from datetime import timedelta

        employee_id = str(action.params.get("employee_id", "")).strip()
        reason = str(action.params.get("reason", f"Removed {employee_id} from schedule period.")).strip()
        run_id_param = action.params.get("schedule_run_id")

        if not employee_id:
            return AIActionExecuteResponse(status="error", message="employee_id required")

        prev = session.get(ScheduleRun, int(run_id_param)) if run_id_param else None
        if not prev:
            prev = session.exec(
                select(ScheduleRun).where(ScheduleRun.status == "draft").order_by(ScheduleRun.created_at.desc())
            ).first()
        if not prev:
            return AIActionExecuteResponse(status="error", message="no_draft_schedule_found")

        before = float(prev.overall_score or 0.0)
        period_start = prev.week_start_date
        for day_offset in range(14):
            target_date = period_start + timedelta(days=day_offset)
            already_blocked = session.exec(
                select(DbTimeOffRequest).where(
                    DbTimeOffRequest.employee_id == employee_id,
                    DbTimeOffRequest.date == target_date,
                    DbTimeOffRequest.status == "approved",
                )
            ).first()
            if not already_blocked:
                session.add(DbTimeOffRequest(
                    employee_id=employee_id,
                    date=target_date,
                    kind="request_off",
                    status="approved",
                    reason=reason,
                ))
        session.commit()

        new_run = generate_and_persist_schedule(
            session=session,
            week_start_date=prev.week_start_date,
            mode=prev.mode,
            redo_of_schedule_run_id=prev.id,
            redo_reason=reason,
        )
        after = float(new_run.overall_score or 0.0)
        result = {
            "new_schedule_run_id": new_run.id,
            "employee_id": employee_id,
            "fairness_before": before,
            "fairness_after": after,
        }
        endpoint = f"/schedules/{prev.id}/remove-employee"
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
    period_days = max(1, days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
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


_HARD_VIOLATION_PREFIXES: frozenset[str] = frozenset([
    "DAILY_MIN_COVERAGE:",
    "LEADERSHIP_MIN_HOURS:",
])


def _has_hard_violations(violations: list[str]) -> bool:
    return any(
        any(v.startswith(prefix) for prefix in _HARD_VIOLATION_PREFIXES)
        for v in violations
    )


def _python_verify_run(session: Session, run_id: int) -> tuple[bool, list[str]]:
    run = session.get(ScheduleRun, run_id)
    if not run:
        return (False, [f"run #{run_id} not found"])

    violations = json.loads(run.violations_json or "[]")
    hard = [v for v in violations if any(v.startswith(p) for p in _HARD_VIOLATION_PREFIXES)]
    return (len(hard) == 0, hard)


def generate_schedule_with_ai_orchestration(
    session: Session,
    week_start_date: date,
    mode: str = "optimized",
    use_ai: bool = True,
) -> tuple[int, str]:
    best_run_id: int | None = None
    best_hard_count: int = 999_999

    prev_run_id: int | None = None
    redo_reason: str | None = None

    for attempt in range(1, 4):
        run = generate_and_persist_schedule(
            session=session,
            week_start_date=week_start_date,
            mode=mode,
            redo_of_schedule_run_id=prev_run_id,
            redo_reason=redo_reason,
        )
        run_id = run.id
        logger.info(
            "generate_schedule: attempt=%s run_id=%s violations=%s",
            attempt, run_id, run.violations_json[:120],
        )

        passed, hard_violations = _python_verify_run(session=session, run_id=run_id)
        hard_count = len(hard_violations)

        if hard_count < best_hard_count:
            best_run_id = run_id
            best_hard_count = hard_count

        if passed:
            logger.info("generate_schedule: Python checks passed on attempt=%s run_id=%s", attempt, run_id)
            break

        redo_reason = (
            f"Attempt {attempt} failed {hard_count} hard constraints: "
            + "; ".join(hard_violations[:5])
        )
        prev_run_id = run_id
    else:
        logger.warning(
            "generate_schedule: all 3 attempts had violations, returning best run_id=%s hard_count=%s",
            best_run_id, best_hard_count,
        )

    winning_run_id = best_run_id or run_id

    if use_ai:
        summary = _ai_summarize_run(session=session, run_id=winning_run_id)
    else:
        summary = f"Schedule run #{winning_run_id} is ready (AI summary skipped)."

    if best_hard_count > 0:
        summary += (
            "\n\nNote: This schedule still has some coverage gaps after 3 generation attempts. "
            "Review the violations panel and consider adjusting employee availability before publishing."
        )

    return (winning_run_id, summary)


def _ai_summarize_run(session: Session, run_id: int) -> str:
    settings = get_settings()

    if not settings.gemini_api_key:
        return f"Schedule run #{run_id} is ready. (AI summary unavailable — no API key configured.)"

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
        from .agent_tools import make_schedule_tools
    except Exception as exc:  # noqa: BLE001
        logger.exception("_ai_summarize_run import failed: %r", exc)
        return f"Schedule run #{run_id} is ready. (AI unavailable.)"

    all_tools = make_schedule_tools(session)
    metrics_tool = next((t for t in all_tools if t.name == "get_metrics"), None)
    if metrics_tool is None:
        return f"Schedule run #{run_id} is ready. (metrics tool not found)"

    model = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        timeout=settings.ai_timeout_seconds,
        temperature=0.2,
    ).bind_tools([metrics_tool])

    system = (
        "You are a scheduling assistant for a small business. "
        "You have been given a completed schedule run id. "
        "Call get_metrics with that run_id, then reply with a concise summary "
        "(4–6 sentences) that covers:\n"
        "  • Coverage percentage — flag if below 90%.\n"
        "  • Overall fairness score.\n"
        "  • Any hard-constraint violations in plain English (not raw code strings).\n"
        "  • Confirm that every working day has at least 1 cook, 1 server, 1 busser, and 1 manager or shift lead.\n"
        "  • A clear recommendation if the owner needs to act before publishing.\n\n"
        "Hard rules to flag if violated:\n"
        "  - Every working day must have a cook, server, busser, and a manager or shift lead.\n"
        "  - The owner should only appear as a last resort.\n"
        "  - No one may be scheduled during approved time off or outside their availability.\n\n"
        "Be direct and friendly. One tool call, then your final answer."
    )
    human = f"Analyze schedule run #{run_id} and give me a summary."

    messages: list = [SystemMessage(content=system), HumanMessage(content=human)]

    try:
        for _ in range(2):
            response = model.invoke(messages)
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                break

            for call in tool_calls:
                if call["name"] == "get_metrics":
                    try:
                        tool_result = metrics_tool.invoke(call["args"])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("get_metrics tool raised: %r", exc)
                        tool_result = json.dumps({"error": str(exc)})
                    messages.append(ToolMessage(content=str(tool_result), tool_call_id=call["id"]))
                else:
                    tool_name = call["name"]
                    messages.append(
                        ToolMessage(
                            content=f'{{"error": "tool {tool_name} not available in this context"}}',
                            tool_call_id=call["id"],
                        )
                    )

        final_content = getattr(messages[-1], "content", "")
        if isinstance(final_content, list):
            summary = " ".join(str(p) for p in final_content).strip()
        else:
            summary = str(final_content).strip()

        return summary or f"Schedule run #{run_id} is ready."

    except Exception as exc:  # noqa: BLE001
        logger.exception("_ai_summarize_run failed: %r", exc)
        code = _categorize_ai_error(str(exc))
        return f"Schedule run #{run_id} is ready. (AI summary failed — {code}.)"
