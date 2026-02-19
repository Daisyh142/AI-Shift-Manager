from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple
from .schemas import Assignment, Availability, Employee, PTO, Role, EmploymentType, Shift
from .priority_graph import employee_priority_score

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

def _get_priority(employee: Employee) -> int:
    return employee_priority_score(
        role=employee.role.value,
        employment_type=employee.employment_type.value,
    )

def generate_greedy_schedule(
    employees: List[Employee],
    availability: List[Availability],
    pto: List[PTO],
    shifts: List[Shift],
    role_cover_map: Dict[str, set[str]] | None = None,
) -> List[Assignment]:
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    assignments_by_employee: Dict[str, List[Shift]] = defaultdict(list)
    
    # Sort employees by priority (highest first)
    sorted_employees = sorted(employees, key=_get_priority, reverse=True)

    assignments: List[Assignment] = []

    role_cover_map = role_cover_map or {}

    for shift in shifts:
        start_min, end_min = _shift_minutes(shift)
        shift_hours = _shift_hours(shift)

        required_staff = getattr(shift, "required_staff", None) or 2
        allowed_roles = None
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})

        # Try to find a leader (Manager/Shift Lead) first for the shift.
        # If none is found, we still fill the shift from any eligible employee.
        leader = None
        for employee in sorted_employees:
            if shift.required_category and employee.category != shift.required_category:
                continue
            if allowed_roles is not None and not any(r in allowed_roles for r in employee.job_roles):
                continue
            if employee.role not in [Role.MANAGER, Role.SHIFT_LEAD]:
                continue
            if _is_eligible(employee, shift, pto_set, availability_map, hours_by_employee, assignments_by_employee, shift_hours):
                leader = employee
                break
        
        if leader:
            assignments.append(Assignment(shift_id=shift.id, employee_id=leader.id))
            assignments_by_employee[leader.id].append(shift)
            hours_by_employee[leader.id] += shift_hours
            remaining = max(0, required_staff - 1)
        else:
            remaining = required_staff

        # Fill remaining staffing requirement with any eligible employees.
        for employee in sorted_employees:
            if remaining <= 0:
                break
            if shift.required_category and employee.category != shift.required_category:
                continue
            if allowed_roles is not None and not any(r in allowed_roles for r in employee.job_roles):
                continue
            if not _is_eligible(
                employee,
                shift,
                pto_set,
                availability_map,
                hours_by_employee,
                assignments_by_employee,
                shift_hours,
            ):
                continue
            assignments.append(Assignment(shift_id=shift.id, employee_id=employee.id))
            assignments_by_employee[employee.id].append(shift)
            hours_by_employee[employee.id] += shift_hours
            remaining -= 1

        # If we still cannot fully staff, owner covers leftover slots.
        while remaining > 0:
            assignments.append(Assignment(shift_id=shift.id, employee_id="OWNER_ID"))
            remaining -= 1

    return assignments

def _is_eligible(employee, shift, pto_set, availability_map, hours_by_employee, assignments_by_employee, shift_hours) -> bool:
    if (employee.id, shift.date.isoformat()) in pto_set:
        return False

    day_key = (employee.id, shift.date.weekday())
    slots = availability_map.get(day_key, [])
    start_min, end_min = _shift_minutes(shift)
    if not any(start_min >= s and end_min <= e for s, e in slots):
        return False

    if hours_by_employee[employee.id] + shift_hours > employee.max_weekly_hours:
        return False

    for other_shift in assignments_by_employee[employee.id]:
        if other_shift.date != shift.date:
            continue
        other_start, other_end = _shift_minutes(other_shift)
        if not (end_min <= other_start or start_min >= other_end):
            return False
            
    return True
