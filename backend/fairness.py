from __future__ import annotations
from typing import List, Dict, Iterable
from .schemas import Employee, Assignment, Shift, FairnessScore
from datetime import datetime

def calculate_fairness(
    employees: Iterable[Employee],
    shifts: Iterable[Shift],
    assignments: Iterable[Assignment],
    weeks_in_period: float = 1.0,
) -> List[FairnessScore]:
    """Scores each employee as a percentage of their requested hours that were scheduled."""
    employee_map = {e.id: e for e in employees}
    shift_map = {s.id: s for s in shifts}
    
    # Track hours assigned to each employee
    assigned_hours: Dict[str, float] = {e.id: 0.0 for e in employees}
    
    for adj in assignments:
        if adj.employee_id == "OWNER_ID":
            continue
            
        shift = shift_map.get(adj.shift_id)
        if shift:
            # Calculate duration in hours
            start_dt = datetime.combine(shift.date, shift.start_time)
            end_dt = datetime.combine(shift.date, shift.end_time)
            duration = (end_dt - start_dt).total_seconds() / 3600
            assigned_hours[adj.employee_id] += duration

    scores = []
    for emp_id, hours in assigned_hours.items():
        emp = employee_map[emp_id]
        reasons = []
        
        # 1. Hours Fairness: How close to requested hours did we get for this period?
        target_hours = emp.required_weekly_hours * weeks_in_period
        if target_hours > 0:
            hour_ratio = min(hours / target_hours, 1.0)
            percentage = hour_ratio * 100
            reasons.append(f"Received {hours:.1f} of {target_hours:.1f} requested hours.")
        else:
            percentage = 100.0
            reasons.append("No specific hours requested.")

        # Flag if the employee was scheduled over their max — does not penalise the score yet.
        max_hours_for_period = emp.max_weekly_hours * weeks_in_period
        if hours > max_hours_for_period:
            reasons.append(f"Warning: Exceeded maximum hours ({max_hours_for_period}).")
        
        scores.append(FairnessScore(
            employee_id=emp_id,
            percentage=round(percentage, 2),
            reasoning=reasons
        ))
        
    return scores
