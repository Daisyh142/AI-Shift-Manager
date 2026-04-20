from __future__ import annotations
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple
from .schemas import Assignment, Availability, Employee, PTO, Role, EmploymentType, Shift
from .priority_graph import employee_priority_score

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


def _candidate_sort_key(
    employee: Employee,
    shift: Shift,
    availability_map: Dict[Tuple[str, int], List[Tuple[int, int]]],
    hours_by_employee: Dict[str, float],
    target_hours_by_employee: Dict[str, float],
    goal_hours_by_employee: Dict[str, float],
    leadership_floor_by_employee: Dict[str, float],
    short_shift_prefer_part_time: bool,
    generation_seed: int = 0,
) -> tuple:
    shift_start, shift_end = _shift_minutes(shift)
    shift_duration = shift_end - shift_start
    slots = availability_map.get((employee.id, shift.date.weekday()), [])
    fitting_slots = [(s, e) for s, e in slots if shift_start >= s and shift_end <= e]
    if not fitting_slots:
        return (9_999, 9_999, 9_999, 9_999, 9_999, 9_999, employee.id)
    best_slot = min(
        fitting_slots,
        key=lambda se: ((se[1] - se[0] - shift_duration), abs(se[0] - shift_start), se[0]),
    )
    slot_start, slot_end = best_slot
    slot_span = max(0, slot_end - slot_start)
    waste = max(0, slot_span - shift_duration)
    exact_fit_rank = 0 if waste == 0 else 1
    constrained_short_rank = (
        0
        if short_shift_prefer_part_time
        and employee.employment_type == EmploymentType.PART_TIME
        and slot_span <= 5 * 60
        else 1
    )
    priority_rank = -_get_priority(employee)
    target_hours = target_hours_by_employee.get(employee.id, 0.0)
    current_hours = hours_by_employee.get(employee.id, 0.0)
    goal_gap = max(0.0, goal_hours_by_employee.get(employee.id, 0.0) - current_hours)
    goal_rank = 0 if goal_gap > 0 else 1
    leadership_floor = leadership_floor_by_employee.get(employee.id, 0.0)
    leadership_floor_gap = max(0.0, leadership_floor - current_hours)
    leadership_floor_pct = (leadership_floor_gap / leadership_floor) if leadership_floor > 0 else 0.0
    leadership_floor_rank = 0 if leadership_floor_gap > 0 else 1
    under_target_gap = max(0.0, target_hours - current_hours)
    seed_rank = hash((employee.id, generation_seed)) % 100_000
    return (
        exact_fit_rank,
        waste,
        goal_rank,
        -goal_gap,
        leadership_floor_rank,
        -leadership_floor_pct,
        seed_rank,
        constrained_short_rank,
        priority_rank,
        -under_target_gap,
        abs(slot_start - shift_start),
    )

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


def _is_owner_employee(employee: Employee) -> bool:
    return employee.role == Role.OWNER or employee.id.upper() == "OWNER_ID"

def generate_greedy_schedule(
    employees: List[Employee],
    availability: List[Availability],
    pto: List[PTO],
    shifts: List[Shift],
    role_cover_map: Dict[str, set[str]] | None = None,
    redo_reason: str | None = None,
    exclude_owner: bool = False,
    max_days_override_shift_employee_pairs: set[tuple[str, str]] | None = None,
    allow_max_days_override: bool = False,
    max_days_per_week: int = 5,
    leadership_min_utilization: float = 0.70,
    requested_hours_delta_by_employee: Dict[str, float] | None = None,
    goal_hours_by_employee: Dict[str, float] | None = None,
    generation_seed: int = 0,
) -> List[Assignment]:
    logger.info(
        "generate_greedy_schedule: seed=%s employees=%d shifts=%d redo=%r",
        generation_seed, len(employees), len(shifts), redo_reason,
    )
    availability_map = _availability_index(availability)
    pto_set = _pto_index(pto)
    hours_by_employee: Dict[str, float] = defaultdict(float)
    hours_by_employee_week: Dict[Tuple[str, str], float] = defaultdict(float)
    assignments_by_employee: Dict[str, List[Shift]] = defaultdict(list)
    days_worked_by_employee_week: Dict[Tuple[str, str], set[str]] = defaultdict(set)

    sorted_employees = sorted(employees, key=_get_priority, reverse=True)
    non_owner_employees = [employee for employee in sorted_employees if not _is_owner_employee(employee)]
    period_multiplier = _period_hour_multiplier(shifts)
    max_hours_limit = {
        employee.id: employee.max_weekly_hours * period_multiplier for employee in employees
    }
    requested_hours_delta_by_employee = requested_hours_delta_by_employee or {}
    goal_hours_by_employee = goal_hours_by_employee or {}
    target_hours_by_employee = {
        employee.id: max(
            0.0,
            employee.required_weekly_hours * period_multiplier + requested_hours_delta_by_employee.get(employee.id, 0.0),
        )
        for employee in employees
    }
    leadership_floor_by_employee = {
        employee.id: max_hours_limit[employee.id] * leadership_min_utilization
        for employee in employees
        if employee.role in (Role.SHIFT_LEAD, Role.MANAGER)
        and employee.employment_type == EmploymentType.FULL_TIME
    }

    assignments: List[Assignment] = []

    role_cover_map = role_cover_map or {}
    max_days_override_shift_employee_pairs = max_days_override_shift_employee_pairs or set()
    _ = redo_reason

    for shift in shifts:
        start_min, end_min = _shift_minutes(shift)
        shift_hours = _shift_hours(shift)

        required_staff = getattr(shift, "required_staff", None) or 2
        allowed_roles = None
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})

        leader = None
        leader_override = False
        _sl_preferred = _is_shift_lead_support_shift(shift)
        leader_pool = sorted(
            [employee for employee in non_owner_employees if employee.role in [Role.MANAGER, Role.SHIFT_LEAD]],
            key=lambda e: (
                (0 if e.role == Role.SHIFT_LEAD else 1) if _sl_preferred else 0,
                _candidate_sort_key(
                    e,
                    shift,
                    availability_map,
                    hours_by_employee,
                    target_hours_by_employee,
                    goal_hours_by_employee,
                    leadership_floor_by_employee,
                    short_shift_prefer_part_time=False,
                    generation_seed=generation_seed,
                ),
            ),
        )
        for employee in leader_pool:
            if shift.required_category != "leadership":
                break
            if not _role_allowed_for_shift(employee, shift):
                continue
            if allowed_roles is not None and not _is_manager_required_shift(shift) and not any(r in allowed_roles for r in employee.job_roles):
                continue
            allowed_by_days, needs_days_override = _max_days_decision(
                employee_id=employee.id,
                shift=shift,
                days_worked_by_employee_week=days_worked_by_employee_week,
                max_days_per_week=max_days_per_week,
                max_days_override_shift_employee_pairs=max_days_override_shift_employee_pairs,
                allow_max_days_override=allow_max_days_override,
            )
            if not allowed_by_days:
                continue
            if _is_eligible(employee, shift, pto_set, availability_map, hours_by_employee, assignments_by_employee, shift_hours, max_hours_limit):
                leader = employee
                leader_override = needs_days_override
                break
        
        if leader:
            assignments.append(
                Assignment(
                    shift_id=shift.id,
                    employee_id=leader.id,
                    override=leader_override,
                    override_reason="COVERAGE_OVERRIDE_MAX_DAYS" if leader_override else None,
                )
            )
            assignments_by_employee[leader.id].append(shift)
            hours_by_employee[leader.id] += shift_hours
            hours_by_employee_week[(leader.id, _week_start_iso(shift.date))] += shift_hours
            days_worked_by_employee_week[(leader.id, _week_start_iso(shift.date))].add(shift.date.isoformat())
            remaining = max(0, required_staff - 1)
        else:
            remaining = required_staff

        candidate_pool = sorted(
            non_owner_employees,
            key=lambda e: _candidate_sort_key(
                e,
                shift,
                availability_map,
                hours_by_employee,
                target_hours_by_employee,
                goal_hours_by_employee,
                leadership_floor_by_employee,
                short_shift_prefer_part_time=shift_hours <= 5.0,
                generation_seed=generation_seed,
            ),
        )
        for employee in candidate_pool:
            if remaining <= 0:
                break
            if shift.required_category and employee.category != shift.required_category:
                continue
            if not _role_allowed_for_shift(employee, shift):
                continue
            if allowed_roles is not None and not _is_manager_required_shift(shift) and not any(r in allowed_roles for r in employee.job_roles):
                continue
            week_key = _week_start_iso(shift.date)
            if hours_by_employee_week[(employee.id, week_key)] + shift_hours > employee.max_weekly_hours:
                continue
            allowed_by_days, needs_days_override = _max_days_decision(
                employee_id=employee.id,
                shift=shift,
                days_worked_by_employee_week=days_worked_by_employee_week,
                max_days_per_week=max_days_per_week,
                max_days_override_shift_employee_pairs=max_days_override_shift_employee_pairs,
                allow_max_days_override=allow_max_days_override,
            )
            if not allowed_by_days:
                continue
            if not _is_eligible(
                employee,
                shift,
                pto_set,
                availability_map,
                hours_by_employee,
                assignments_by_employee,
                shift_hours,
                max_hours_limit,
            ):
                continue
            assignments.append(
                Assignment(
                    shift_id=shift.id,
                    employee_id=employee.id,
                    override=needs_days_override,
                    override_reason="COVERAGE_OVERRIDE_MAX_DAYS" if needs_days_override else None,
                )
            )
            assignments_by_employee[employee.id].append(shift)
            hours_by_employee[employee.id] += shift_hours
            hours_by_employee_week[(employee.id, week_key)] += shift_hours
            days_worked_by_employee_week[(employee.id, _week_start_iso(shift.date))].add(shift.date.isoformat())
            remaining -= 1

        if not exclude_owner:
            while remaining > 0:
                assignments.append(
                    Assignment(
                        shift_id=shift.id,
                        employee_id="OWNER_ID",
                        override=True,
                        override_reason="OWNER_LAST_RESORT_INFEASIBLE",
                    )
                )
                remaining -= 1

    total_required = sum(s.required_staff for s in shifts)
    logger.info(
        "generate_greedy_schedule: first-pass done — %d/%d slots filled",
        len(assignments), total_required,
    )

    assignments = _gap_fill_to_open_limit_per_week(
        assignments=assignments,
        shifts=shifts,
        non_owner_employees=non_owner_employees,
        availability_map=availability_map,
        pto_set=pto_set,
        hours_by_employee=hours_by_employee,
        assignments_by_employee=assignments_by_employee,
        max_hours_limit=max_hours_limit,
        days_worked_by_employee_week=days_worked_by_employee_week,
        max_days_per_week=max_days_per_week,
        leadership_floor_by_employee=leadership_floor_by_employee,
    )

    logger.info(
        "generate_greedy_schedule: final total=%d assignments after gap-fill",
        len(assignments),
    )
    return assignments

def _gap_fill_to_open_limit_per_week(
    assignments: List[Assignment],
    shifts: List[Shift],
    non_owner_employees: List[Employee],
    availability_map: Dict[Tuple[str, int], List[Tuple[int, int]]],
    pto_set: set[Tuple[str, str]],
    hours_by_employee: Dict[str, float],
    assignments_by_employee: Dict[str, List[Shift]],
    max_hours_limit: Dict[str, float],
    days_worked_by_employee_week: Dict[Tuple[str, str], set[str]],
    max_days_per_week: int,
    leadership_floor_by_employee: Dict[str, float],
    max_open_per_week: int = 2,
) -> List[Assignment]:
    assigned_counts: Dict[str, int] = defaultdict(int)
    for a in assignments:
        assigned_counts[a.shift_id] += 1

    shifts_by_week: Dict[str, List[Shift]] = defaultdict(list)
    for shift in shifts:
        shifts_by_week[_week_start_iso(shift.date)].append(shift)

    priority_order = {"leadership": 0, "cook": 1, "server": 2, "busser": 3}

    for week_key, week_shifts in sorted(shifts_by_week.items()):
        open_shifts = [
            s for s in week_shifts
            if assigned_counts.get(s.id, 0) < (s.required_staff or 1)
        ]
        slots_to_fill_count = max(0, len(open_shifts) - max_open_per_week)
        logger.info(
            "_gap_fill: week=%s open_shifts=%d max_allowed=%d need_to_fill=%d",
            week_key, len(open_shifts), max_open_per_week, slots_to_fill_count,
        )
        if slots_to_fill_count == 0:
            continue

        open_shifts.sort(key=lambda s: priority_order.get(s.required_category or "", 9))

        def _urgency(e: Employee) -> float:
            floor = leadership_floor_by_employee.get(e.id, 0.0)
            if floor <= 0:
                return 0.0
            return max(0.0, floor - hours_by_employee.get(e.id, 0.0)) / floor

        managers = sorted(
            [e for e in non_owner_employees if e.role == Role.MANAGER],
            key=_urgency, reverse=True,
        )
        shift_leads = sorted(
            [e for e in non_owner_employees if e.role == Role.SHIFT_LEAD],
            key=_urgency, reverse=True,
        )
        ft_regulars = [
            e for e in non_owner_employees
            if e.role not in (Role.MANAGER, Role.SHIFT_LEAD)
            and e.employment_type == EmploymentType.FULL_TIME
        ]
        pt_regulars = [
            e for e in non_owner_employees
            if e.role not in (Role.MANAGER, Role.SHIFT_LEAD)
            and e.employment_type == EmploymentType.PART_TIME
        ]
        fill_candidates = managers + shift_leads + ft_regulars + pt_regulars

        filled = 0
        for shift in open_shifts:
            if filled >= slots_to_fill_count:
                break
            if assigned_counts.get(shift.id, 0) >= (shift.required_staff or 1):
                continue
            shift_hours = _shift_hours(shift)
            for employee in fill_candidates:
                is_leader_emp = employee.role in (Role.MANAGER, Role.SHIFT_LEAD)
                if not is_leader_emp and shift.required_category and employee.category != shift.required_category:
                    continue
                if is_leader_emp:
                    if not _is_eligible_leadership_override(
                        employee, shift, pto_set, availability_map,
                        hours_by_employee, max_hours_limit, assignments_by_employee,
                    ):
                        continue
                else:
                    if not _is_eligible(
                        employee, shift, pto_set, availability_map,
                        hours_by_employee, assignments_by_employee,
                        shift_hours, max_hours_limit,
                    ):
                        continue
                worked_days = days_worked_by_employee_week[(employee.id, week_key)]
                if (not is_leader_emp) and shift.date.isoformat() not in worked_days and len(worked_days) >= max_days_per_week:
                    continue
                is_leader = employee.role in (Role.MANAGER, Role.SHIFT_LEAD)
                assignments.append(Assignment(
                    shift_id=shift.id,
                    employee_id=employee.id,
                    override=True,
                    override_reason="GAP_FILL_LEADERSHIP_COVER" if is_leader else "GAP_FILL_OPEN_SLOT_LIMIT",
                ))
                assignments_by_employee[employee.id].append(shift)
                hours_by_employee[employee.id] += shift_hours
                days_worked_by_employee_week[(employee.id, week_key)].add(shift.date.isoformat())
                assigned_counts[shift.id] += 1
                filled += 1
                break

    return assignments


def _is_eligible(employee, shift, pto_set, availability_map, hours_by_employee, assignments_by_employee, shift_hours, max_hours_limit) -> bool:
    if (employee.id, shift.date.isoformat()) in pto_set:
        return False

    day_key = (employee.id, shift.date.weekday())
    slots = availability_map.get(day_key, [])
    start_min, end_min = _shift_minutes(shift)
    if not any(start_min >= s and end_min <= e for s, e in slots):
        return False

    if hours_by_employee[employee.id] + shift_hours > max_hours_limit[employee.id]:
        return False

    for other_shift in assignments_by_employee[employee.id]:
        if other_shift.date != shift.date:
            continue
        other_start, other_end = _shift_minutes(other_shift)
        if not (end_min <= other_start or start_min >= other_end):
            return False
            
    return True


def _is_eligible_leadership_override(
    employee,
    shift,
    pto_set,
    availability_map,
    hours_by_employee,
    max_hours_limit,
    assignments_by_employee,
) -> bool:
    if (employee.id, shift.date.isoformat()) in pto_set:
        return False
    if not _role_allowed_for_shift(employee, shift):
        return False
    day_key = (employee.id, shift.date.weekday())
    slots = availability_map.get(day_key, [])
    start_min, end_min = _shift_minutes(shift)
    if not any(start_min >= s and end_min <= e for s, e in slots):
        return False
    shift_hours = _shift_hours(shift)
    if hours_by_employee[employee.id] + shift_hours > max_hours_limit[employee.id]:
        return False
    for other_shift in assignments_by_employee[employee.id]:
        if other_shift.date != shift.date:
            continue
        other_start, other_end = _shift_minutes(other_shift)
        if not (end_min <= other_start or start_min >= other_end):
            return False
    return True
