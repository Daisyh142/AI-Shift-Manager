from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, delete, select

from ..baseline_scheduler import generate_baseline_schedule
from ..constraints import validate_assignments
from ..fairness import calculate_fairness
from ..seed import seed_shifts_for_period
from ..models import (
    Assignment as DbAssignment,
    Availability as DbAvailability,
    CoverageRequest as DbCoverageRequest,
    Employee as DbEmployee,
    EmployeeHoursPreference as DbEmployeeHoursPreference,
    EmployeeJobRole as DbEmployeeJobRole,
    ScheduleRun,
    Shift as DbShift,
    TimeOffRequest as DbTimeOffRequest,
)
from ..schemas import (
    Assignment,
    Availability,
    Employee,
    EmploymentType,
    PTO,
    Role,
    Shift,
    ScheduleChangeRequest,
    TimeOffKind,
    TimeOffStatus,
)
from ..scheduler import generate_greedy_schedule
from ..coverage import cover_set_for_required_role

logger = logging.getLogger(__name__)

def _redo_options_from_reason(redo_reason: str | None) -> dict[str, bool]:
    reason_lower = (redo_reason or "").lower()
    exclude_owner = "owner" in reason_lower and any(
        x in reason_lower for x in ["not", "don't", "do not", "exclude", "off schedule", "off the schedule"]
    )
    return {"exclude_owner": True} if exclude_owner else {}


def _resolve_schedule_options(
    redo_reason: str | None,
    schedule_options: dict[str, bool] | None,
) -> dict[str, bool]:
    options = {"exclude_owner": True, "allow_max_days_override": False}
    options.update(_redo_options_from_reason(redo_reason))
    if schedule_options:
        for k, v in schedule_options.items():
            if isinstance(v, bool):
                options[k] = v
    return options


def _approved_coverage_override_pairs(session: Session) -> set[tuple[str, str]]:
    rows = session.exec(
        select(DbCoverageRequest).where(
            DbCoverageRequest.status == "approved",
            DbCoverageRequest.cover_employee_id.is_not(None),
        )
    ).all()
    return {
        (row.shift_id, row.cover_employee_id)
        for row in rows
        if row.cover_employee_id
    }


def _ensure_weekend_peak_availability(session: Session) -> None:
    removed_fri = False
    for emp_id in ("c3", "s3"):
        fri_rows = session.exec(
            select(DbAvailability).where(
                DbAvailability.employee_id == emp_id,
                DbAvailability.day_of_week == 4,
            )
        ).all()
        for row in fri_rows:
            session.delete(row)
            removed_fri = True
    if removed_fri:
        session.commit()
        logger.info("_ensure_weekend_peak_availability: removed Friday availability for c3/s3")

    needed: list[tuple[str, int, int, int]] = [
        ("s1", 0, 15, 23), ("s1", 2, 15, 23), ("s1", 3, 15, 23),
        ("s1", 4, 15, 23), ("s1", 5, 15, 23), ("s1", 6, 15, 23),
        ("s2", 5, 9, 17),
        ("s3", 5, 9, 23),
        ("s3", 6, 9, 23),
        ("c3", 5, 9, 23),
        ("c3", 6, 9, 23),
        ("b2", 6, 15, 23),
        ("b3", 5, 15, 23),
    ]
    changed = False
    for emp_id, dow, start_h, end_h in needed:
        exists = session.exec(
            select(DbAvailability).where(
                DbAvailability.employee_id == emp_id,
                DbAvailability.day_of_week == dow,
                DbAvailability.start_time == time(start_h, 0),
                DbAvailability.end_time == time(end_h, 0),
            )
        ).first()
        if not exists:
            session.add(DbAvailability(
                employee_id=emp_id, day_of_week=dow,
                start_time=time(start_h, 0), end_time=time(end_h, 0),
            ))
            changed = True
    if changed:
        session.commit()
        logger.info("_ensure_weekend_peak_availability: inserted missing availability rows")


def _ensure_default_shifts_for_period(session: Session, period_start_date: date) -> None:
    period_end = period_start_date + timedelta(days=13)
    logger.info("_ensure_default_shifts: seeding period %s – %s", period_start_date, period_end)
    _ensure_weekend_peak_availability(session)
    seed_shifts_for_period(session, period_start_date)
    shift_rows = session.exec(
        select(DbShift).where(DbShift.date >= period_start_date, DbShift.date <= period_end)
    ).all()
    deleted = 0
    for row in shift_rows:
        sid = row.id
        dow = row.date.weekday()
        is_friday = dow == 4
        is_weekend_day = dow >= 5
        is_mon_or_tue = dow <= 1
        if (
            "_pt1_" in sid
            or "_pt2_" in sid
            or "_eve_" in sid
            or "_mid_" in sid
            or ("ld_mgr_close_" in sid and (is_weekend_day or is_mon_or_tue))
            or ("ld_mgr_open_" in sid and is_weekend_day)
            or ("ld_lead_open_" in sid and dow in (0, 3))
            or ("_pm_" in sid and is_friday)
            or ("_close_" in sid and is_weekend_day and not sid.startswith("ld_"))
        ):
            session.delete(row)
            deleted += 1
            continue
        if "ld_lead_support_" in sid:
            row.start_time = time(15, 0)
            row.end_time = time(23, 0)
        if "_close_" in sid and not sid.startswith("ld_"):
            correct_start = time(16, 0) if dow in (1, 2) else time(15, 0)
            row.start_time = correct_start
            row.end_time = time(23, 0)
        if row.required_category != "leadership":
            row.required_staff = 1
    session.commit()
    logger.info(
        "_ensure_default_shifts: trimmed %d optional rows, %d rows remain for period",
        deleted, len(shift_rows) - deleted,
    )


def _upgrade_rigid_period_shifts_if_needed(session: Session, period_start_date: date) -> None:
    period_end = period_start_date + timedelta(days=13)
    shift_rows = session.exec(
        select(DbShift).where(DbShift.date >= period_start_date, DbShift.date <= period_end)
    ).all()
    if not shift_rows:
        return

    rigid_pairs = {(time(9, 0), time(16, 0)), (time(16, 0), time(23, 0))}
    current_pairs = {(row.start_time, row.end_time) for row in shift_rows}
    if current_pairs != rigid_pairs:
        return

    grouped: dict[tuple[date, str | None, str | None], list[DbShift]] = {}
    for row in shift_rows:
        key = (row.date, row.required_category, row.required_role)
        grouped.setdefault(key, []).append(row)

    replacement_rows: list[DbShift] = []
    close_templates = [(time(15, 0), time(23, 0)), (time(16, 0), time(23, 0))]
    mid_templates = [(time(11, 0), time(19, 0)), (time(12, 0), time(20, 0)), (time(13, 0), time(21, 0))]
    for (shift_date, category, required_role), rows in sorted(grouped.items(), key=lambda item: (item[0][0], str(item[0][1]), str(item[0][2]))):
        total_staff = sum(max(1, int(row.required_staff)) for row in rows)
        close_template = close_templates[shift_date.toordinal() % len(close_templates)]
        mid_template = mid_templates[shift_date.toordinal() % len(mid_templates)]
        if total_staff <= 2:
            split_templates = [
                [(time(9, 0), time(15, 0)), (time(15, 0), time(23, 0))],
                [(time(9, 0), time(16, 0)), (time(16, 0), time(23, 0))],
                [(time(9, 0), time(17, 0)), (time(17, 0), time(23, 0))],
            ]
            templates = list(split_templates[shift_date.toordinal() % len(split_templates)])
        else:
            templates = [(time(9, 0), time(17, 0)), mid_template, close_template]
            if (category or "") != "leadership":
                templates.append((time(16, 0), time(21, 0)))
        if total_staff >= 4:
            templates.append((time(16, 0), time(20, 0)))
        slots = min(len(templates), max(1, total_staff))
        templates = templates[:slots]

        base_staff = total_staff // slots
        remainder = total_staff % slots
        for idx, (start_time, end_time) in enumerate(templates):
            required_staff = base_staff + (1 if idx < remainder else 0)
            if required_staff <= 0:
                continue
            category_prefix = (category or "gen")[:2]
            role_prefix = (required_role or "role").replace("_", "")[:3]
            effective_required_role = required_role
            if category == "leadership":
                if idx == 0:
                    shift_id = f"ld_mgr_{shift_date.isoformat()}_mix{idx+1}"
                    effective_required_role = "manager"
                else:
                    shift_id = f"ld_lead_{shift_date.isoformat()}_mix{idx+1}"
            else:
                shift_id = f"{category_prefix}_{role_prefix}_{shift_date.isoformat()}_mix{idx+1}"
            replacement_rows.append(
                DbShift(
                    id=shift_id,
                    date=shift_date,
                    start_time=start_time,
                    end_time=end_time,
                    required_staff=required_staff,
                    required_category=category,
                    required_role=effective_required_role,
                )
            )

    session.exec(delete(DbShift).where(DbShift.date >= period_start_date, DbShift.date <= period_end))
    for row in replacement_rows:
        session.add(row)
    session.commit()


def _shift_minutes(shift: Shift) -> tuple[int, int]:
    return (
        shift.start_time.hour * 60 + shift.start_time.minute,
        shift.end_time.hour * 60 + shift.end_time.minute,
    )


def _shift_hours(shift: Shift) -> float:
    return (max(0, _shift_minutes(shift)[1] - _shift_minutes(shift)[0])) / 60.0


def _period_hour_multiplier(shifts: list[Shift]) -> float:
    if not shifts:
        return 1.0
    days = (max(s.date for s in shifts) - min(s.date for s in shifts)).days + 1
    return max(1.0, days / 7.0)


def _is_manager_required_shift(shift: Shift) -> bool:
    return bool(shift.required_category == "leadership" and ("_mgr_" in shift.id or shift.required_role == "manager"))


def _assigned_hours_by_employee(shifts: list[Shift], assignments: list[Assignment]) -> dict[str, float]:
    shift_by_id = {s.id: s for s in shifts}
    totals: dict[str, float] = {}
    for assignment in assignments:
        if assignment.employee_id == "OWNER_ID":
            continue
        shift = shift_by_id.get(assignment.shift_id)
        if not shift:
            continue
        totals[assignment.employee_id] = totals.get(assignment.employee_id, 0.0) + _shift_hours(shift)
    return totals


def _assigned_hours_for_run_employee(session: Session, schedule_run_id: int, employee_id: str) -> float:
    run = session.get(ScheduleRun, schedule_run_id)
    if not run:
        return 0.0
    period_end = run.week_start_date + timedelta(days=13)
    shift_rows = session.exec(
        select(DbShift).where(DbShift.date >= run.week_start_date, DbShift.date <= period_end)
    ).all()
    shift_map = {row.id: row for row in shift_rows}
    total = 0.0
    assignment_rows = session.exec(
        select(DbAssignment).where(
            DbAssignment.schedule_run_id == schedule_run_id,
            DbAssignment.employee_id == employee_id,
        )
    ).all()
    for row in assignment_rows:
        shift = shift_map.get(row.shift_id)
        if not shift:
            continue
        total += (max(0, (shift.end_time.hour * 60 + shift.end_time.minute) - (shift.start_time.hour * 60 + shift.start_time.minute))) / 60.0
    return total


def _leadership_floor_violations(
    *,
    employees: list[Employee],
    availability: list[Availability],
    shifts: list[Shift],
    assignments: list[Assignment],
    role_cover_map: dict[str, set[str]],
    min_utilization: float,
) -> list[str]:
    if min_utilization <= 0:
        return []
    hours_by_employee = _assigned_hours_by_employee(shifts, assignments)
    availability_index: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for slot in availability:
        key = (slot.employee_id, slot.day_of_week)
        availability_index.setdefault(key, []).append(
            (slot.start_time.hour * 60 + slot.start_time.minute, slot.end_time.hour * 60 + slot.end_time.minute)
        )
    period_multiplier = _period_hour_multiplier(shifts)
    violations: list[str] = []
    for employee in employees:
        if employee.role != Role.SHIFT_LEAD or employee.employment_type != EmploymentType.FULL_TIME:
            continue
        max_hours = employee.max_weekly_hours * period_multiplier
        floor_hours = max_hours * min_utilization
        assigned = hours_by_employee.get(employee.id, 0.0)
        if assigned + 0.01 >= floor_hours:
            continue
        feasible_upper_bound = 0.0
        for shift in shifts:
            if shift.required_category and employee.category != shift.required_category and employee.role not in (Role.MANAGER, Role.SHIFT_LEAD):
                continue
            if shift.required_role:
                allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})
                if not any(role_name in allowed_roles for role_name in employee.job_roles):
                    continue
            shift_start, shift_end = _shift_minutes(shift)
            windows = availability_index.get((employee.id, shift.date.weekday()), [])
            if any(shift_start >= s and shift_end <= e for s, e in windows):
                feasible_upper_bound += _shift_hours(shift)
        violations.append(
            "LEADERSHIP_MIN_HOURS_NOT_MET:"
            f"severity=SOFT:employee_id={employee.id}:assigned={assigned:.2f}:"
            f"floor={floor_hours:.2f}:feasible_upper_bound={feasible_upper_bound:.2f}"
        )
    return violations


def _infeasible_candidate_diagnostics(
    *,
    employees: list[Employee],
    availability: list[Availability],
    pto: list[PTO],
    shifts: list[Shift],
    assignments: list[Assignment],
    role_cover_map: dict[str, set[str]],
    max_days_per_week: int = 5,
) -> list[str]:
    shift_by_id = {s.id: s for s in shifts}
    assigned_by_shift: dict[str, int] = {}
    for a in assignments:
        assigned_by_shift[a.shift_id] = assigned_by_shift.get(a.shift_id, 0) + 1

    availability_index: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for slot in availability:
        key = (slot.employee_id, slot.day_of_week)
        availability_index.setdefault(key, []).append(
            (slot.start_time.hour * 60 + slot.start_time.minute, slot.end_time.hour * 60 + slot.end_time.minute)
        )
    pto_set = {(p.employee_id, p.date.isoformat()) for p in pto}
    assigned_shifts_by_employee: dict[str, list[Shift]] = {}
    hours_by_employee: dict[str, float] = {}
    days_worked_by_employee_week: dict[tuple[str, str], set[str]] = {}
    for a in assignments:
        if a.employee_id == "OWNER_ID":
            continue
        shift = shift_by_id.get(a.shift_id)
        if not shift:
            continue
        assigned_shifts_by_employee.setdefault(a.employee_id, []).append(shift)
        hours_by_employee[a.employee_id] = hours_by_employee.get(a.employee_id, 0.0) + _shift_hours(shift)
        week_key = (shift.date - timedelta(days=shift.date.weekday())).isoformat()
        days_worked_by_employee_week.setdefault((a.employee_id, week_key), set()).add(shift.date.isoformat())
    period_multiplier = _period_hour_multiplier(shifts)
    max_hours_limit = {e.id: e.max_weekly_hours * period_multiplier for e in employees}

    diagnostics: list[str] = []
    for shift in shifts:
        assigned = assigned_by_shift.get(shift.id, 0)
        required = shift.required_staff or 1
        if assigned >= required:
            continue
        candidate_reasons: list[str] = []
        allowed_roles = None
        if shift.required_role:
            allowed_roles = role_cover_map.get(shift.required_role, {shift.required_role})
        shift_start, shift_end = _shift_minutes(shift)
        shift_hours = _shift_hours(shift)
        for employee in employees:
            if employee.role == Role.OWNER or employee.id.upper() == "OWNER_ID":
                continue
            if shift.required_category and employee.category != shift.required_category:
                continue
            if _is_manager_required_shift(shift) and employee.role != Role.MANAGER:
                continue
            if allowed_roles is not None and not _is_manager_required_shift(shift) and not any(r in allowed_roles for r in employee.job_roles):
                continue
            reasons: list[str] = []
            if (employee.id, shift.date.isoformat()) in pto_set:
                reasons.append("pto")
            slots = availability_index.get((employee.id, shift.date.weekday()), [])
            if not any(shift_start >= s and shift_end <= e for s, e in slots):
                reasons.append("availability")
            if hours_by_employee.get(employee.id, 0.0) + shift_hours > max_hours_limit[employee.id]:
                reasons.append("max_hours")
            for other_shift in assigned_shifts_by_employee.get(employee.id, []):
                if other_shift.date != shift.date:
                    continue
                other_start, other_end = _shift_minutes(other_shift)
                if not (shift_end <= other_start or shift_start >= other_end):
                    reasons.append("overlap")
                    break
            week_key = (shift.date - timedelta(days=shift.date.weekday())).isoformat()
            worked_days = days_worked_by_employee_week.get((employee.id, week_key), set())
            if shift.date.isoformat() not in worked_days and len(worked_days) >= max_days_per_week:
                reasons.append("max_days_per_week")
            if reasons:
                candidate_reasons.append(f"{employee.id}={'|'.join(sorted(set(reasons)))}")
        category = shift.required_category or "unspecified"
        range_text = f"{shift.start_time.strftime('%H:%M')}-{shift.end_time.strftime('%H:%M')}"
        diagnostics.append(
            f"infeasible_candidates:{shift.id}:category={category}:range={range_text}:{';'.join(candidate_reasons) or 'none'}"
        )
    return diagnostics


def _to_schema_employee(
    e: DbEmployee,
    job_roles: list[str],
    requested_weekly_hours_override: float | None = None,
) -> Employee:
    try:
        role = Role(e.role)
    except ValueError:
        role = Role.REGULAR

    try:
        employment_type = EmploymentType(e.employment_type)
    except ValueError:
        employment_type = EmploymentType.PART_TIME

    return Employee(
        id=e.id,
        name=e.name,
        max_weekly_hours=e.max_weekly_hours,
        required_weekly_hours=requested_weekly_hours_override
        if requested_weekly_hours_override is not None
        else e.required_weekly_hours,
        role=role,
        employment_type=employment_type,
        active=bool(getattr(e, "active", True)),
        pto_balance_hours=e.pto_balance_hours,
        category=e.category,
        job_roles=job_roles,
    )


def _to_schema_availability(a: DbAvailability) -> Availability:
    return Availability(
        employee_id=a.employee_id,
        day_of_week=a.day_of_week,
        start_time=a.start_time,
        end_time=a.end_time,
    )


def _to_schema_time_off(p: DbTimeOffRequest) -> PTO:
    kind = TimeOffKind(p.kind) if p.kind in TimeOffKind._value2member_map_ else TimeOffKind.REQUEST_OFF
    return PTO(
        employee_id=p.employee_id,
        date=p.date,
        kind=kind,
        hours=p.hours,
        reason=p.reason,
    )


def _to_schema_shift(s: DbShift) -> Shift:
    return Shift(
        id=s.id,
        date=s.date,
        start_time=s.start_time,
        end_time=s.end_time,
        required_role=s.required_role,
        required_staff=s.required_staff,
        required_category=s.required_category,
    )


def build_period_inputs(session: Session, period_start_date: date) -> tuple[
    list[Employee], list[Availability], list[PTO], list[Shift]
]:
    employee_rows = session.exec(select(DbEmployee).where(DbEmployee.active == True)).all()  # noqa: E712
    job_role_rows = session.exec(select(DbEmployeeJobRole)).all()
    active_employee_ids = {e.id for e in employee_rows}
    job_roles_by_employee: dict[str, list[str]] = {}
    for r in job_role_rows:
        if r.employee_id not in active_employee_ids:
            continue
        job_roles_by_employee.setdefault(r.employee_id, []).append(r.role_name)

    period_end = period_start_date + timedelta(days=13)
    period_weeks = max(1.0, ((period_end - period_start_date).days + 1) / 7.0)
    preference_rows = session.exec(
        select(DbEmployeeHoursPreference).where(
            DbEmployeeHoursPreference.period_start == period_start_date,
            DbEmployeeHoursPreference.period_end == period_end,
        )
    ).all()
    weekly_hours_override_by_employee = {
        row.employee_id: float(row.requested_hours) / period_weeks for row in preference_rows
    }

    employees = [
        _to_schema_employee(
            e,
            job_roles=sorted(job_roles_by_employee.get(e.id, [])),
            requested_weekly_hours_override=weekly_hours_override_by_employee.get(e.id),
        )
        for e in employee_rows
    ]
    availability = [
        _to_schema_availability(a)
        for a in session.exec(select(DbAvailability)).all()
        if a.employee_id in active_employee_ids
    ]
    pto = [
        _to_schema_time_off(p)
        for p in session.exec(
            select(DbTimeOffRequest).where(
                DbTimeOffRequest.status == TimeOffStatus.APPROVED.value,
                DbTimeOffRequest.date >= period_start_date,
                DbTimeOffRequest.date <= period_end,
            )
        ).all()
        if p.employee_id in active_employee_ids
    ]

    shifts = [
        _to_schema_shift(s)
        for s in session.exec(
            select(DbShift).where(DbShift.date >= period_start_date, DbShift.date <= period_end)
        ).all()
    ]

    def _shift_priority(s: Shift) -> int:
        if s.required_category == "leadership" and ("_mgr_" in s.id or s.required_role == "manager"):
            return 0
        if s.required_category == "leadership":
            return 1
        return 2

    shifts.sort(key=lambda s: (s.date, s.start_time, _shift_priority(s), s.id))
    return employees, availability, pto, shifts


def generate_and_persist_schedule(
    *,
    session: Session,
    week_start_date: date,
    mode: str,
    redo_of_schedule_run_id: int | None = None,
    redo_reason: str | None = None,
    schedule_options: dict[str, bool] | None = None,
    schedule_change_request: ScheduleChangeRequest | None = None,
) -> ScheduleRun:
    logger.info(
        "generate_and_persist_schedule: week_start=%s mode=%s redo_of=%s",
        week_start_date, mode, redo_of_schedule_run_id,
    )
    _ensure_default_shifts_for_period(session, week_start_date)
    _upgrade_rigid_period_shifts_if_needed(session, week_start_date)
    employees, availability, pto, shifts = build_period_inputs(session, week_start_date)
    logger.info(
        "generate_and_persist_schedule: loaded %d employees, %d shifts for period",
        len(employees), len(shifts),
    )
    resolved_options = _resolve_schedule_options(redo_reason, schedule_options)
    exclude_owner = bool(resolved_options.get("exclude_owner", True))
    allow_max_days_override = bool(resolved_options.get("allow_max_days_override", False))
    leadership_min_utilization = 0.70
    max_days_override_shift_employee_pairs = _approved_coverage_override_pairs(session)
    requested_hours_delta_by_employee: dict[str, float] = {}
    goal_hours_by_employee: dict[str, float] = {}
    target_utilization_goal_by_employee: dict[str, float] = {}
    if schedule_change_request and schedule_change_request.type == "ADJUST_HOURS":
        requested_hours_delta_by_employee[schedule_change_request.employee_id] = float(schedule_change_request.delta_hours or 0.0)
        if schedule_change_request.constraints.max_days_per_week:
            max_days_per_week = int(schedule_change_request.constraints.max_days_per_week)
        else:
            max_days_per_week = 5
    elif schedule_change_request and schedule_change_request.type == "SET_UTILIZATION_TARGET":
        period_multiplier = _period_hour_multiplier(shifts)
        employee = next((e for e in employees if e.id == schedule_change_request.employee_id), None)
        if employee:
            max_hours_for_period = employee.max_weekly_hours * period_multiplier
            target_util = float(schedule_change_request.target_utilization or 0.0)
            goal_hours_by_employee[schedule_change_request.employee_id] = max_hours_for_period * target_util
            target_utilization_goal_by_employee[schedule_change_request.employee_id] = target_util
        if schedule_change_request.constraints.max_days_per_week:
            max_days_per_week = int(schedule_change_request.constraints.max_days_per_week)
        else:
            max_days_per_week = 5
    else:
        max_days_per_week = 5

    required_roles = sorted({s.required_role for s in shifts if s.required_role})
    role_cover_map = {r: cover_set_for_required_role(session, r) for r in required_roles}

    if mode not in {"baseline", "optimized"}:
        raise ValueError("mode_must_be_baseline_or_optimized")

    generation_seed = int(datetime.now().timestamp() * 1000) % 100_000
    seeded_shifts = sorted(
        shifts,
        key=lambda s: (
            s.date,
            s.start_time,
            hash((s.id, generation_seed)) % 100_000,
            s.id,
        ),
    )

    def _generate(exclude_owner_now: bool) -> list[Assignment]:
        if mode == "baseline":
            return generate_baseline_schedule(
                week_start_seed=week_start_date.toordinal(),
                employees=employees,
                availability=availability,
                pto=pto,
                shifts=seeded_shifts,
                role_cover_map=role_cover_map,
                redo_reason=redo_reason,
                exclude_owner=exclude_owner_now,
                max_days_override_shift_employee_pairs=max_days_override_shift_employee_pairs,
                allow_max_days_override=allow_max_days_override,
                max_days_per_week=max_days_per_week,
            )
        return generate_greedy_schedule(
            employees=employees,
            availability=availability,
            pto=pto,
            shifts=seeded_shifts,
            role_cover_map=role_cover_map,
            redo_reason=redo_reason,
            exclude_owner=exclude_owner_now,
            max_days_override_shift_employee_pairs=max_days_override_shift_employee_pairs,
            allow_max_days_override=allow_max_days_override,
            max_days_per_week=max_days_per_week,
            leadership_min_utilization=leadership_min_utilization,
            requested_hours_delta_by_employee=requested_hours_delta_by_employee,
            goal_hours_by_employee=goal_hours_by_employee,
            generation_seed=generation_seed,
        )

    assignments_without_owner = _generate(exclude_owner_now=True)
    violations_without_owner = validate_assignments(
        employees=employees,
        availability=availability,
        pto=pto,
        shifts=shifts,
        assignments=assignments_without_owner,
        role_cover_map=role_cover_map,
    )
    infeasible_without_owner = any(v.startswith("infeasible_") for v in violations_without_owner)

    assignments = assignments_without_owner
    violations = list(violations_without_owner)
    if not exclude_owner and infeasible_without_owner:
        assignments = _generate(exclude_owner_now=False)
        violations = validate_assignments(
            employees=employees,
            availability=availability,
            pto=pto,
            shifts=shifts,
            assignments=assignments,
            role_cover_map=role_cover_map,
        )
        if not any(v.startswith("infeasible_") for v in violations_without_owner):
            assignments = assignments_without_owner
            violations = list(violations_without_owner)

    if infeasible_without_owner:
        violations.extend(
            _infeasible_candidate_diagnostics(
                employees=employees,
                availability=availability,
                pto=pto,
                shifts=shifts,
                assignments=assignments_without_owner,
                role_cover_map=role_cover_map,
            )
        )
    violations.extend(
        _leadership_floor_violations(
            employees=employees,
            availability=availability,
            shifts=shifts,
            assignments=assignments,
            role_cover_map=role_cover_map,
            min_utilization=leadership_min_utilization,
        )
    )
    if schedule_change_request and schedule_change_request.type == "SET_UTILIZATION_TARGET":
        fairness_by_employee = {score.employee_id: score for score in calculate_fairness(
            employees=employees,
            shifts=shifts,
            assignments=assignments,
            weeks_in_period=max(1.0, (len(sorted({s.date for s in shifts})) / 7.0) if shifts else 1.0),
        )}
        target_emp = fairness_by_employee.get(schedule_change_request.employee_id)
        target_utilization = float(schedule_change_request.target_utilization or 0.0)
        achieved_utilization = float(target_emp.utilization if target_emp else 0.0)
        if schedule_change_request.strict and achieved_utilization + 1e-6 < target_utilization:
            violations.append(
                "infeasible_utilization_target:"
                f"employee_id={schedule_change_request.employee_id}:"
                f"target={target_utilization:.3f}:achieved={achieved_utilization:.3f}:"
                "reason=availability_or_coverage_constraints"
            )

    unique_shift_days = sorted({s.date for s in shifts})
    if unique_shift_days:
        period_days = (unique_shift_days[-1] - unique_shift_days[0]).days + 1
    else:
        period_days = 7
    weeks_in_period = max(1.0, period_days / 7.0)

    fairness_scores = calculate_fairness(
        employees=employees,
        shifts=shifts,
        assignments=assignments,
        weeks_in_period=weeks_in_period,
    )
    overall_score = (
        sum(s.percentage for s in fairness_scores) / len(fairness_scores) if fairness_scores else 0.0
    )

    run = ScheduleRun(
        week_start_date=week_start_date,
        mode=mode,
        redo_of_schedule_run_id=redo_of_schedule_run_id,
        redo_reason=redo_reason,
        violations_json=json.dumps(violations),
        fairness_json=json.dumps([s.model_dump() for s in fairness_scores]),
        overall_score=overall_score,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for a in assignments:
        session.add(
            DbAssignment(
                schedule_run_id=run.id,
                shift_id=a.shift_id,
                employee_id=a.employee_id,
                override=a.override,
                override_reason=a.override_reason,
            )
        )
    session.commit()

    if schedule_change_request and schedule_change_request.type in {"ADJUST_HOURS", "SET_UTILIZATION_TARGET"}:
        before_hours = (
            _assigned_hours_for_run_employee(session, redo_of_schedule_run_id, schedule_change_request.employee_id)
            if redo_of_schedule_run_id
            else 0.0
        )
        after_hours = _assigned_hours_by_employee(shifts, assignments).get(schedule_change_request.employee_id, 0.0)
        period_multiplier = _period_hour_multiplier(shifts)
        employee = next((e for e in employees if e.id == schedule_change_request.employee_id), None)
        max_hours_for_period = (employee.max_weekly_hours * period_multiplier) if employee else 0.0
        before_util = (before_hours / max_hours_for_period) if max_hours_for_period > 0 else 0.0
        after_util = (after_hours / max_hours_for_period) if max_hours_for_period > 0 else 0.0
        target_utilization = (
            float(schedule_change_request.target_utilization or 0.0)
            if schedule_change_request.type == "SET_UTILIZATION_TARGET"
            else None
        )
        achieved_target = (
            bool(after_util + 1e-6 >= target_utilization)
            if target_utilization is not None
            else bool(after_hours + 1e-6 >= (before_hours + float(schedule_change_request.delta_hours or 0.0)))
        )
        infeasible_reason = next((v for v in violations if v.startswith("infeasible_utilization_target:")), None)
        logger.info(
            "chat_schedule_redo run_id=%s employee_id=%s request_type=%s before_hours=%.2f after_hours=%.2f before_util=%.4f after_util=%.4f achieved_target=%s infeasible_reason=%s requested_delta_hours=%s target_utilization=%s",
            run.id,
            schedule_change_request.employee_id,
            schedule_change_request.type,
            before_hours,
            after_hours,
            before_util,
            after_util,
            achieved_target,
            infeasible_reason,
            schedule_change_request.delta_hours,
            schedule_change_request.target_utilization,
        )

    hard_v = [v for v in violations if any(v.startswith(p) for p in (
        "DAILY_MIN_COVERAGE:", "MISSING_CATEGORY_COVERAGE:",
        "MISSING_MANAGER_COVERAGE:", "LEADERSHIP_MIN_HOURS:",
    ))]
    logger.info(
        "generate_and_persist_schedule: run_id=%s overall_score=%.3f "
        "total_violations=%d hard_violations=%d",
        run.id, overall_score or 0.0, len(violations), len(hard_v),
    )
    if hard_v:
        logger.warning(
            "generate_and_persist_schedule: HARD VIOLATIONS in run #%s: %s",
            run.id, "; ".join(hard_v[:5]),
        )
    return run

