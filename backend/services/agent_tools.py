from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from ..models import (
    Assignment,
    Employee as DbEmployee,
    ScheduleRun,
    Shift,
    TimeOffRequest as DbTimeOffRequest,
)
from .scheduling_service import generate_and_persist_schedule

logger = logging.getLogger(__name__)


def make_schedule_tools(session: Session) -> list:
    from langchain_core.tools import tool

    @tool
    def get_employee_data(filter: str) -> str:
        """Return employee records as JSON."""
        rows = session.exec(select(DbEmployee).where(DbEmployee.active == True)).all()  # noqa: E712

        f = (filter or "all").lower().strip()
        if f.startswith("role:"):
            role_value = f[len("role:"):].strip()
            rows = [e for e in rows if e.role == role_value]
        elif f == "pending_pto":
            pending_ids = {
                r.employee_id
                for r in session.exec(
                    select(DbTimeOffRequest).where(DbTimeOffRequest.status == "pending")
                ).all()
            }
            rows = [e for e in rows if e.id in pending_ids]

        return json.dumps([
            {
                "id": e.id,
                "name": e.name,
                "role": e.role,
                "category": e.category,
                "employment_type": e.employment_type,
                "max_weekly_hours": e.max_weekly_hours,
                "required_weekly_hours": e.required_weekly_hours,
                "pto_balance_hours": e.pto_balance_hours,
            }
            for e in rows
        ])

    @tool
    def generate_draft_schedule(week_start_date: str) -> str:
        """Generate a draft schedule for a week start date."""
        try:
            start = date.fromisoformat(week_start_date.strip())
        except ValueError:
            return json.dumps({"error": f"Invalid date '{week_start_date}'. Use YYYY-MM-DD."})

        try:
            run = generate_and_persist_schedule(
                session=session,
                week_start_date=start,
                mode="optimized",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("generate_draft_schedule tool failed: %r", exc)
            return json.dumps({"error": str(exc)})

        violations = json.loads(run.violations_json or "[]")
        return json.dumps({
            "run_id": run.id,
            "week_start_date": str(run.week_start_date),
            "status": run.status,
            "overall_fairness_score": run.overall_score,
            "violations_count": len(violations),
            "violations": violations[:10],
        })

    @tool
    def override_constraint(request_id: str) -> str:
        """Approve a pending time-off request by id."""
        try:
            rid = int(request_id)
        except ValueError:
            return json.dumps({"error": f"request_id must be a number, got: '{request_id}'"})

        req = session.get(DbTimeOffRequest, rid)
        if not req:
            return json.dumps({"error": f"TimeOffRequest id={rid} not found."})
        if req.status == "approved":
            return json.dumps({"status": "already_approved", "request_id": rid})

        req.status = "approved"
        req.decided_at = datetime.now(timezone.utc)
        session.add(req)
        session.commit()
        session.refresh(req)

        return json.dumps({
            "status": "approved",
            "request_id": rid,
            "employee_id": req.employee_id,
            "date": str(req.date),
            "kind": req.kind,
        })

    @tool
    def get_metrics(run_id: str) -> str:
        """Return schedule metrics by run id."""
        try:
            rid = int(run_id)
        except ValueError:
            return json.dumps({"error": f"run_id must be a number, got: '{run_id}'"})

        run = session.get(ScheduleRun, rid)
        if not run:
            return json.dumps({"error": f"ScheduleRun id={rid} not found."})

        violations = json.loads(run.violations_json or "[]")
        fairness_rows = json.loads(run.fairness_json or "[]")

        assignments = session.exec(
            select(Assignment).where(Assignment.schedule_run_id == rid)
        ).all()

        period_end = run.week_start_date + timedelta(days=13)
        shifts = session.exec(
            select(Shift).where(
                Shift.date >= run.week_start_date,
                Shift.date <= period_end,
            )
        ).all()

        assigned_counts: dict[str, int] = {}
        for a in assignments:
            assigned_counts[a.shift_id] = assigned_counts.get(a.shift_id, 0) + 1

        fully_staffed = sum(
            1 for s in shifts if assigned_counts.get(s.id, 0) >= s.required_staff
        )
        coverage_percent = (fully_staffed / len(shifts) * 100.0) if shifts else 100.0

        return json.dumps({
            "run_id": rid,
            "status": run.status,
            "week_start_date": str(run.week_start_date),
            "overall_fairness_score": run.overall_score,
            "coverage_percent": round(coverage_percent, 1),
            "total_shifts": len(shifts),
            "fully_staffed_shifts": fully_staffed,
            "violations_count": len(violations),
            "violations": violations[:10],
            "per_employee_fairness": fairness_rows,
        })

    return [get_employee_data, generate_draft_schedule, override_constraint, get_metrics]
