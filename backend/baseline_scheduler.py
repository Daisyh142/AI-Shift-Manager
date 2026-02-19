from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from .schemas import Assignment, Availability, Employee, PTO, Role, Shift


def _shift_minutes(shift: Shift) -> Tuple[int, int]:
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    return start, end


def _shift_hours(shift: Shift) -> float:
    start_dt = datetime.combine(shift.date, shift.start_time)
    end_dt = datetime.combine(shift.date, shift.end_time)
    return max(0.0, (end_dt - start_dt).total_seconds() / 3600)


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
) -> bool:
    if (employee.id, shift.date.isoformat()) in pto_set:
        return False

    day_key = (employee.id, shift.date.weekday())
    slots = availability_map.get(day_key, [])
    start_min, end_min = _shift_minutes(shift)
    if not any(start_min >= s and end_min <= e for s, e in slots):
        return False

    if hours_by_employee[employee.id] + shift_hours > employee.max_weekly_hours:
        return False

    for other_shift in assigned_shifts_by_employee[employee.id]:
        if other_shift.date != shift.date:
            continue
        other_start, other_end = _shift_minutes(other_shift)
        if not (end_min <= other_start or start_min >= other_end):
            return False

    return True


def generate_baseline_schedule(
    *,
    week_start_seed: int,
    employees: List[Employee],
    availability: List[Availability],
    pto: List[PTO],
    shifts: List[Shift],
    default_required_staff: int = 2,
    role_cover_map: Dict[str, set[str]] | None = None,
) -> List[Assignment]:
    """
    Baseline scheduler (for analytics): randomized, minimal strategy.

    What it does:
    - Tries to staff each shift up to required staff count.
    - Still respects hard constraints (availability/PTO/max hours/no overlap).
    - Does NOT optimize fairness or role priority ordering.

    Connection to analytics:
    - Because it is consistently \"worse\" than optimized, we can compute %
      improvements across weeks (baseline vs optimized).
    """
    rng = random.Random(week_start_seed)
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    assigned_shifts_by_employee: Dict[str, List[Shift]] = defaultdict(list)

    assignments: List[Assignment] = []

    role_cover_map = role_cover_map or {}

    for shift in shifts:
        start_min, end_min = _shift_minutes(shift)
        _ = (start_min, end_min)  # kept for readability symmetry
        shift_hours = _shift_hours(shift)

        required_staff = getattr(shift, "required_staff", None) or default_required_staff
        allowed_roles = None
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})

        # Step 1: pick a leader if possible; otherwise owner works.
        shuffled = employees[:]
        rng.shuffle(shuffled)

        leader = next(
            (
                e
                for e in shuffled
                if e.role in [Role.MANAGER, Role.SHIFT_LEAD]
                and (not shift.required_category or e.category == shift.required_category)
                and (allowed_roles is None or any(r in allowed_roles for r in e.job_roles))
                and _is_eligible(
                    e,
                    shift,
                    pto_set,
                    availability_map,
                    hours_by_employee,
                    assigned_shifts_by_employee,
                    shift_hours,
                )
            ),
            None,
        )

        if leader:
            assignments.append(Assignment(shift_id=shift.id, employee_id=leader.id))
            assigned_shifts_by_employee[leader.id].append(shift)
            hours_by_employee[leader.id] += shift_hours
        else:
            assignments.append(Assignment(shift_id=shift.id, employee_id="OWNER_ID"))

        remaining = max(0, required_staff - 1)

        # Step 2: fill remaining slots with any eligible regular employees (random order).
        for e in shuffled:
            if remaining <= 0:
                break
            if e.role != Role.REGULAR:
                continue
            if shift.required_category and e.category != shift.required_category:
                continue
            if allowed_roles is not None and not any(r in allowed_roles for r in e.job_roles):
                continue
            if not _is_eligible(
                e,
                shift,
                pto_set,
                availability_map,
                hours_by_employee,
                assigned_shifts_by_employee,
                shift_hours,
            ):
                continue
            assignments.append(Assignment(shift_id=shift.id, employee_id=e.id))
            assigned_shifts_by_employee[e.id].append(shift)
            hours_by_employee[e.id] += shift_hours
            remaining -= 1

    return assignments

