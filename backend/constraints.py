from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Tuple
from .schemas import Assignment, Availability, Employee, EmploymentType, PTO, Role, Shift

logger = logging.getLogger(__name__)

def _is_manager_required_shift(shift: Shift) -> bool:
    return bool(shift.required_category == "leadership" and ("_mgr_" in shift.id or shift.required_role == "manager"))


def _is_shift_lead_support_shift(shift: Shift) -> bool:
    return bool(shift.required_category == "leadership" and "_lead_" in shift.id)


def _role_allowed_for_shift(employee: Employee, shift: Shift) -> bool:
    if _is_manager_required_shift(shift):
        return employee.role == Role.MANAGER
    if _is_shift_lead_support_shift(shift):
        return employee.role in [Role.MANAGER, Role.SHIFT_LEAD]
    return True

def _shift_hours(shift: Shift) -> float:
    start_dt = datetime.combine(shift.date, shift.start_time)
    end_dt = datetime.combine(shift.date, shift.end_time)
    return max(0.0, (end_dt - start_dt).total_seconds() / 3600)

def _availability_index(
    availability: Iterable[Availability],
) -> Dict[Tuple[str, int], List[Tuple[int, int]]]:
    index: Dict[Tuple[str, int], List[Tuple[int, int]]] = defaultdict(list)
    for slot in availability:
        start = slot.start_time.hour * 60 + slot.start_time.minute
        end = slot.end_time.hour * 60 + slot.end_time.minute
        index[(slot.employee_id, slot.day_of_week)].append((start, end))
    return index

def _pto_index(pto: Iterable[PTO]) -> set[Tuple[str, str]]:
    return {(entry.employee_id, entry.date.isoformat()) for entry in pto}

def _shift_minutes(shift: Shift) -> Tuple[int, int]:
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    return start, end


def _period_hour_multiplier(shifts: Iterable[Shift]) -> float:
    shift_list = list(shifts)
    if not shift_list:
        return 1.0
    first = min(shift.date for shift in shift_list)
    last = max(shift.date for shift in shift_list)
    days = (last - first).days + 1
    return max(1.0, days / 7.0)

def validate_assignments(
    employees: Iterable[Employee],
    availability: Iterable[Availability],
    pto: Iterable[PTO],
    shifts: Iterable[Shift],
    assignments: Iterable[Assignment],
    role_cover_map: Dict[str, set[str]] | None = None,
) -> List[str]:
    employee_map = {employee.id: employee for employee in employees}
    shift_list = list(shifts)
    shift_map = {shift.id: shift for shift in shift_list}
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)

    violations: List[str] = []
    assigned_by_employee: Dict[str, List[Shift]] = defaultdict(list)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    role_cover_map = role_cover_map or {}
    period_multiplier = _period_hour_multiplier(shift_list)
    
    assignment_list = list(assignments)

    shift_staffing: Dict[str, List[Employee | str]] = defaultdict(list)
    for a in assignment_list:
        emp = employee_map.get(a.employee_id)
        if emp:
            shift_staffing[a.shift_id].append(emp)
        elif a.employee_id == "OWNER_ID":
            shift_staffing[a.shift_id].append("OWNER")

    for shift in shift_list:
        staff = shift_staffing.get(shift.id, [])
        assigned = len(staff)
        required = getattr(shift, "required_staff", None) or 1
        manager_assigned = sum(
            1
            for member in staff
            if member != "OWNER" and isinstance(member, Employee) and member.role == Role.MANAGER
        )
        if assigned < required:
            range_text = f"{shift.start_time.strftime('%H:%M')}-{shift.end_time.strftime('%H:%M')}"
            category = shift.required_category or "unspecified"
            missing_count = required - assigned
            violations.append(
                f"UNDERSTAFFED_SHIFT:{shift.id}:missing_count={missing_count}:category={category}:range={range_text}"
            )
            violations.append(
                f"infeasible_coverage_gap:{shift.id}:category={category}:range={range_text}:assigned={assigned}:required={required}"
            )
            if assigned == 0:
                violations.append(
                    f"MISSING_CATEGORY_COVERAGE:{shift.id}:category={category}:range={range_text}"
                )
                if shift.required_role:
                    violations.append(
                        f"MISSING_ROLE_COVERAGE:{shift.id}:role={shift.required_role}:range={range_text}"
                    )
                violations.append(
                    f"infeasible_category_empty:{shift.id}:category={category}:range={range_text}"
                )
        if _is_manager_required_shift(shift) and manager_assigned < required:
            range_text = f"{shift.start_time.strftime('%H:%M')}-{shift.end_time.strftime('%H:%M')}"
            violations.append(
                f"MISSING_MANAGER_COVERAGE:{shift.id}:missing_count={required - manager_assigned}:range={range_text}"
            )

    days_worked_by_employee_week: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    for assignment in assignment_list:
        if assignment.employee_id == "OWNER_ID":
            continue

        shift = shift_map.get(assignment.shift_id)
        employee = employee_map.get(assignment.employee_id)
        if not shift or not employee:
            violations.append(f"invalid_assignment:{assignment.shift_id}")
            continue

        if getattr(shift, "required_category", None) and employee.category != shift.required_category:
            violations.append(f"category_violation:{employee.id}:{shift.id}")
        if not _role_allowed_for_shift(employee, shift):
            violations.append(f"role_eligibility_violation:{employee.id}:{shift.id}")
        if shift.required_role:
            if not _is_manager_required_shift(shift):
                allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})
                if not any(r in allowed_roles for r in employee.job_roles):
                    violations.append(f"role_eligibility_violation:{employee.id}:{shift.id}")

        if (employee.id, shift.date.isoformat()) in pto_set:
            violations.append(f"pto_violation:{employee.id}:{shift.id}")

        avail_key = (employee.id, shift.date.weekday())
        start_min, end_min = _shift_minutes(shift)
        availability_slots = availability_map.get(avail_key, [])
        if not any(start_min >= s and end_min <= e for s, e in availability_slots):
            violations.append(f"availability_violation:{employee.id}:{shift.id}")

        for other_shift in assigned_by_employee[employee.id]:
            if other_shift.date != shift.date:
                continue
            other_start, other_end = _shift_minutes(other_shift)
            overlap = not (end_min <= other_start or start_min >= other_end)
            if overlap:
                violations.append(f"overlap_violation:{employee.id}:{shift.id}")
                break

        shift_hours = _shift_hours(shift)
        hours_by_employee[employee.id] += shift_hours
        if hours_by_employee[employee.id] > employee.max_weekly_hours * period_multiplier:
            violations.append(f"max_hours_violation:{employee.id}")

        week_key = (shift.date - timedelta(days=shift.date.weekday())).isoformat()
        day_iso = shift.date.isoformat()
        worked_days = days_worked_by_employee_week[(employee.id, week_key)]
        is_new_day = day_iso not in worked_days
        if is_new_day and len(worked_days) >= 5:
            has_coverage_override = bool(assignment.override) and assignment.override_reason == "COVERAGE_OVERRIDE_MAX_DAYS"
            if has_coverage_override:
                violations.append(
                    f"max_days_per_week_override:{employee.id}:{week_key}:{shift.id}"
                )
            else:
                violations.append(
                    f"MAX_DAYS_PER_WEEK_EXCEEDED:{employee.id}:{week_key}:{shift.id}"
                )
        worked_days.add(day_iso)

        assigned_by_employee[employee.id].append(shift)

    required_categories = {"cook", "server", "busser"}
    days_with_shifts: set[str] = {s.date.isoformat() for s in shift_list}
    for day_iso in sorted(days_with_shifts):
        covered_categories: set[str] = set()
        has_leadership = False
        for a in assignment_list:
            shift = shift_map.get(a.shift_id)
            if not shift or shift.date.isoformat() != day_iso:
                continue
            if a.employee_id == "OWNER_ID":
                has_leadership = True
                continue
            emp = employee_map.get(a.employee_id)
            if not emp:
                continue
            if emp.category in required_categories:
                covered_categories.add(emp.category)
            if emp.role in (Role.MANAGER, Role.SHIFT_LEAD):
                has_leadership = True
        missing: list[str] = sorted(required_categories - covered_categories)
        if not has_leadership:
            missing.append("leadership")
        if missing:
            violations.append(
                f"DAILY_MIN_COVERAGE:{day_iso}:missing={','.join(missing)}"
            )

    for emp in employee_map.values():
        if emp.role not in (Role.SHIFT_LEAD, Role.MANAGER):
            continue
        if emp.employment_type != EmploymentType.FULL_TIME:
            continue
        hours = hours_by_employee.get(emp.id, 0.0)
        floor = emp.max_weekly_hours * period_multiplier * 0.50
        if hours < floor:
            violations.append(
                f"LEADERSHIP_MIN_HOURS:{emp.id}:assigned={hours:.1f}h:floor={floor:.1f}h"
            )

    hard_prefixes = (
        "DAILY_MIN_COVERAGE:", "MISSING_CATEGORY_COVERAGE:",
        "MISSING_MANAGER_COVERAGE:", "LEADERSHIP_MIN_HOURS:",
    )
    hard = [v for v in violations if any(v.startswith(p) for p in hard_prefixes)]
    if violations:
        logger.warning(
            "validate_assignments: %d total violations (%d hard): %s",
            len(violations), len(hard),
            "; ".join(violations[:6]),
        )
    else:
        logger.info("validate_assignments: 0 violations — schedule is clean")
    return violations
