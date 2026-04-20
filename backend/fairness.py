from __future__ import annotations
import logging
from typing import List, Dict, Iterable, Optional
from .schemas import Employee, Assignment, Shift, FairnessScore, Role
from datetime import datetime

logger = logging.getLogger(__name__)

def calculate_fairness(
    employees: Iterable[Employee],
    shifts: Iterable[Shift],
    assignments: Iterable[Assignment],
    weeks_in_period: float = 1.0,
    requested_hours_by_employee: Optional[Dict[str, float]] = None,
) -> List[FairnessScore]:
    employee_list = list(employees)
    shift_map = {s.id: s for s in shifts}
    requested_hours_by_employee = requested_hours_by_employee or {}

    assigned_hours: Dict[str, float] = {e.id: 0.0 for e in employee_list}

    for adj in assignments:
        if adj.employee_id == "OWNER_ID":
            continue
        shift = shift_map.get(adj.shift_id)
        if shift:
            start_dt = datetime.combine(shift.date, shift.start_time)
            end_dt = datetime.combine(shift.date, shift.end_time)
            duration = (end_dt - start_dt).total_seconds() / 3600
            assigned_hours[adj.employee_id] += duration

    max_hours_by_employee: Dict[str, float] = {
        e.id: max(0.0, e.max_weekly_hours * weeks_in_period)
        for e in employee_list
    }
    effective_requested_hours: Dict[str, float] = {
        e.id: requested_hours_by_employee.get(
            e.id, max(0.0, e.required_weekly_hours * weeks_in_period)
        )
        for e in employee_list
    }
    utilization_by_employee: Dict[str, float] = {}
    for emp_id, hours in assigned_hours.items():
        max_hours = max_hours_by_employee.get(emp_id, 0.0)
        if max_hours <= 0:
            utilization = 0.0
        else:
            utilization = min(1.0, max(0.0, hours / max_hours))
        utilization_by_employee[emp_id] = utilization

    mean_utilization = (
        sum(utilization_by_employee.values()) / len(utilization_by_employee)
        if utilization_by_employee
        else 0.0
    )

    scores = []
    for emp_id, hours in assigned_hours.items():
        max_hours_for_period = max_hours_by_employee.get(emp_id, 0.0)
        req_hours = effective_requested_hours.get(emp_id, 0.0)
        utilization = utilization_by_employee.get(emp_id, 0.0)
        fairness_ratio = max(0.0, 1.0 - abs(utilization - mean_utilization))
        reasons = [
            f"Assigned {hours:.1f}h out of requested {req_hours:.1f}h (utilization {utilization * 100:.1f}%).",
            f"Team mean utilization is {mean_utilization * 100:.1f}%; fairness penalizes distance from this mean.",
        ]
        if hours > max_hours_for_period > 0:
            reasons.append(f"Warning: Exceeded maximum hours cap ({max_hours_for_period:.1f}h).")

        scores.append(
            FairnessScore(
                employee_id=emp_id,
                percentage=round(fairness_ratio * 100.0, 2),
                reasoning=reasons,
                assigned_hours=round(hours, 2),
                requested_hours=round(req_hours, 2),
                delta_hours=round(hours - req_hours, 2),
                max_hours=round(max_hours_for_period, 2),
                utilization=round(utilization, 4),
            )
        )

    emp_map = {e.id: e for e in employee_list}
    for s in scores:
        emp = emp_map.get(s.employee_id)
        is_leader = emp and emp.role in (Role.MANAGER, Role.SHIFT_LEAD)
        level = logging.WARNING if (is_leader and s.utilization < 0.50) else logging.DEBUG
        logger.log(
            level,
            "fairness: employee=%s role=%s utilization=%.1f%% assigned=%.1fh max=%.1fh",
            s.employee_id, emp.role if emp else "?",
            s.utilization * 100, s.assigned_hours, s.max_hours,
        )
    return scores
