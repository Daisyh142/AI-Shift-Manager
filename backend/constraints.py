from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Tuple
from .schemas import Assignment, Availability, Employee, PTO, Role, Shift

def _shift_hours(shift: Shift) -> float:
    """Returns the duration of a shift in hours."""
    start_dt = datetime.combine(shift.date, shift.start_time)
    end_dt = datetime.combine(shift.date, shift.end_time)
    return max(0.0, (end_dt - start_dt).total_seconds() / 3600)

def _availability_index(
    availability: Iterable[Availability],
) -> Dict[Tuple[str, int], List[Tuple[int, int]]]:
    """Indexes availability slots by (employee_id, day_of_week) for O(1) lookup."""
    index: Dict[Tuple[str, int], List[Tuple[int, int]]] = defaultdict(list)
    for slot in availability:
        start = slot.start_time.hour * 60 + slot.start_time.minute
        end = slot.end_time.hour * 60 + slot.end_time.minute
        index[(slot.employee_id, slot.day_of_week)].append((start, end))
    return index

def _pto_index(pto: Iterable[PTO]) -> set[Tuple[str, str]]:
    """Returns a set of (employee_id, date_iso) pairs for fast PTO lookup."""
    return {(entry.employee_id, entry.date.isoformat()) for entry in pto}

def _shift_minutes(shift: Shift) -> Tuple[int, int]:
    """Returns the shift's start and end times as minutes since midnight."""
    start = shift.start_time.hour * 60 + shift.start_time.minute
    end = shift.end_time.hour * 60 + shift.end_time.minute
    return start, end

def validate_assignments(
    employees: Iterable[Employee],
    availability: Iterable[Availability],
    pto: Iterable[PTO],
    shifts: Iterable[Shift],
    assignments: Iterable[Assignment],
    role_cover_map: Dict[str, set[str]] | None = None,
) -> List[str]:
    """Validates a set of schedule assignments and returns a list of violation strings."""
    employee_map = {employee.id: employee for employee in employees}
    shift_map = {shift.id: shift for shift in shifts}
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)

    violations: List[str] = []
    assigned_by_employee: Dict[str, List[Shift]] = defaultdict(list)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    role_cover_map = role_cover_map or {}
    
    # Track who is working each shift
    shift_staffing: Dict[str, List[Employee | str]] = defaultdict(list)
    for a in assignments:
        emp = employee_map.get(a.employee_id)
        if emp:
            shift_staffing[a.shift_id].append(emp)
        elif a.employee_id == "OWNER_ID":
            shift_staffing[a.shift_id].append("OWNER")

    # Check leadership constraint for each shift
    for shift_id, staff in shift_staffing.items():
        has_leader = any(
            (isinstance(e, Employee) and e.role in [Role.MANAGER, Role.SHIFT_LEAD]) or e == "OWNER"
            for e in staff
        )
        has_regular = any(isinstance(e, Employee) and e.role == Role.REGULAR for e in staff)
        
        if has_regular and not has_leader:
            violations.append(f"leadership_violation:shift_{shift_id}_needs_manager_or_lead")

    for assignment in assignments:
        if assignment.employee_id == "OWNER_ID":
            # The owner doesn't have max hours, PTO, or availability constraints here
            continue

        shift = shift_map.get(assignment.shift_id)
        employee = employee_map.get(assignment.employee_id)
        if not shift or not employee:
            violations.append(f"invalid_assignment:{assignment.shift_id}")
            continue

        # Role eligibility (job roles) + category matching
        if getattr(shift, "required_category", None) and employee.category != shift.required_category:
            violations.append(f"category_violation:{employee.id}:{shift.id}")
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})
            if not any(r in allowed_roles for r in employee.job_roles):
                violations.append(f"role_eligibility_violation:{employee.id}:{shift.id}")

        if (employee.id, shift.date.isoformat()) in pto_set:
            violations.append(f"pto_violation:{employee.id}:{shift.id}")

        day_key = (employee.id, shift.date.weekday())
        start_min, end_min = _shift_minutes(shift)
        availability_slots = availability_map.get(day_key, [])
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
        if hours_by_employee[employee.id] > employee.max_weekly_hours:
            violations.append(f"max_hours_violation:{employee.id}")

        assigned_by_employee[employee.id].append(shift)

    return violations
