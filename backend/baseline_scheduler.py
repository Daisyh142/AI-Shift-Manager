from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from .schemas import Assignment, Availability, Employee, EmploymentType, PTO, Role, Shift


def _shift_minutes(shift: Shift) -> Tuple[int, int]:
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    return start, end


def _shift_hours(shift: Shift) -> float:
    start_dt = datetime.combine(shift.date, shift.start_time)
    end_dt = datetime.combine(shift.date, shift.end_time)
    return max(0.0, (end_dt - start_dt).total_seconds() / 3600)


def _period_hour_multiplier(shifts: List[Shift]) -> float:
    if not shifts:
        return 1.0
    days = (max(s.date for s in shifts) - min(s.date for s in shifts)).days + 1
    return max(1.0, days / 7.0)


def _week_start_iso(shift_date: date) -> str:
    return (shift_date - timedelta(days=shift_date.weekday())).isoformat()


def _max_days_decision(
    *,
    employee_id: str,
    shift: Shift,
    days_worked_by_employee_week: Dict[Tuple[str, str], set[str]],
    max_days_per_week: int,
    max_days_override_shift_employee_pairs: set[tuple[str, str]],
    allow_max_days_override: bool,
) -> tuple[bool, bool]:
    week_key = _week_start_iso(shift.date)
    day_key = shift.date.isoformat()
    worked_days = days_worked_by_employee_week[(employee_id, week_key)]
    if day_key in worked_days:
        return True, False
    if len(worked_days) < max_days_per_week:
        return True, False
    if allow_max_days_override or (shift.id, employee_id) in max_days_override_shift_employee_pairs:
        return True, True
    return False, False


def _availability_index(
    availability: List[Availability],
) -> Dict[Tuple[str, int], List[Tuple[int, int]]]:
    index: Dict[Tuple[str, int], List[Tuple[int, int]]] = defaultdict(list)
    for slot in availability:
        start = slot.start_time.hour * 60 + slot.start_time.minute
        end = slot.end_time.hour * 60 + slot.end_time.minute
        index[(slot.employee_id, slot.day_of_week)].append((start, end))
    return index


def _pto_index(pto: List[PTO]) -> set[Tuple[str, str]]:
    return {(entry.employee_id, entry.date.isoformat()) for entry in pto}


def _is_eligible(
    employee: Employee,
    shift: Shift,
    pto_set: set[Tuple[str, str]],
    availability_map: Dict[Tuple[str, int], List[Tuple[int, int]]],
    hours_by_employee: Dict[str, float],
    assigned_shifts_by_employee: Dict[str, List[Shift]],
    shift_hours: float,
    max_hours_limit: Dict[str, float],
) -> bool:
    if (employee.id, shift.date.isoformat()) in pto_set:
        return False

    day_key = (employee.id, shift.date.weekday())
    slots = availability_map.get(day_key, [])
    start_min, end_min = _shift_minutes(shift)
    if not any(start_min >= s and end_min <= e for s, e in slots):
        return False

    if hours_by_employee[employee.id] + shift_hours > max_hours_limit[employee.id]:
        return False

    for other_shift in assigned_shifts_by_employee[employee.id]:
        if other_shift.date != shift.date:
            continue
        other_start, other_end = _shift_minutes(other_shift)
        if not (end_min <= other_start or start_min >= other_end):
            return False

    return True


def _is_owner_employee(employee: Employee) -> bool:
    return employee.role == Role.OWNER or employee.id.upper() == "OWNER_ID"


def generate_baseline_schedule(
    *,
    week_start_seed: int,
    employees: List[Employee],
    availability: List[Availability],
    pto: List[PTO],
    shifts: List[Shift],
    default_required_staff: int = 2,
    role_cover_map: Dict[str, set[str]] | None = None,
    redo_reason: str | None = None,
    exclude_owner: bool = False,
    max_days_override_shift_employee_pairs: set[tuple[str, str]] | None = None,
    allow_max_days_override: bool = False,
    max_days_per_week: int = 5,
) -> List[Assignment]:
    rng = random.Random(week_start_seed)
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    assigned_shifts_by_employee: Dict[str, List[Shift]] = defaultdict(list)
    days_worked_by_employee_week: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    period_multiplier = _period_hour_multiplier(shifts)
    max_hours_limit = {
        employee.id: employee.max_weekly_hours * period_multiplier for employee in employees
    }

    assignments: List[Assignment] = []

    role_cover_map = role_cover_map or {}
    max_days_override_shift_employee_pairs = max_days_override_shift_employee_pairs or set()
    _ = redo_reason

    for shift in shifts:
        start_min, end_min = _shift_minutes(shift)
        _ = (start_min, end_min)
        shift_hours = _shift_hours(shift)

        required_staff = getattr(shift, "required_staff", None) or default_required_staff
        allowed_roles = None
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})

        shuffled = employees[:]
        rng.shuffle(shuffled)
        non_owner_shuffled = [employee for employee in shuffled if not _is_owner_employee(employee)]
        if shift_hours <= 4.5:
            non_owner_shuffled.sort(key=lambda e: (e.employment_type != EmploymentType.PART_TIME, e.id))

        remaining = required_staff
        for e in non_owner_shuffled:
            if remaining <= 0:
                break
            if not (allowed_roles is None or any(r in allowed_roles for r in e.job_roles)):
                continue
            if shift.required_category and e.category != shift.required_category:
                continue
            allowed_by_days, needs_days_override = _max_days_decision(
                employee_id=e.id,
                shift=shift,
                days_worked_by_employee_week=days_worked_by_employee_week,
                max_days_per_week=max_days_per_week,
                max_days_override_shift_employee_pairs=max_days_override_shift_employee_pairs,
                allow_max_days_override=allow_max_days_override,
            )
            if not allowed_by_days:
                continue
            if not _is_eligible(
                e,
                shift,
                pto_set,
                availability_map,
                hours_by_employee,
                assigned_shifts_by_employee,
                shift_hours,
                max_hours_limit,
            ):
                continue
            assignments.append(
                Assignment(
                    shift_id=shift.id,
                    employee_id=e.id,
                    override=needs_days_override,
                    override_reason="COVERAGE_OVERRIDE_MAX_DAYS" if needs_days_override else None,
                )
            )
            assigned_shifts_by_employee[e.id].append(shift)
            hours_by_employee[e.id] += shift_hours
            days_worked_by_employee_week[(e.id, _week_start_iso(shift.date))].add(shift.date.isoformat())
            remaining -= 1

        while remaining > 0 and not exclude_owner:
            assignments.append(
                Assignment(
                    shift_id=shift.id,
                    employee_id="OWNER_ID",
                    override=True,
                    override_reason="OWNER_LAST_RESORT_INFEASIBLE",
                )
            )
            remaining -= 1

    return assignments

