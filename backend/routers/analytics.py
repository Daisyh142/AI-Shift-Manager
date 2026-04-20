from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlmodel import Session

from ..db import get_session

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_date(d: str) -> date:
    return date.fromisoformat(d)


@router.get("/summary", response_model=dict)
def analytics_summary(
    start: str = Query(..., description="ISO date, inclusive (period start)"),
    end: str = Query(..., description="ISO date, inclusive (period start)"),
    mode: str = Query(default="optimized", pattern="^(baseline|optimized)$"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    start_d = _parse_date(start)
    end_d = _parse_date(end)

    understaff_sql = text(
        """
        WITH assigned AS (
          SELECT schedule_run_id, shift_id, COUNT(*) AS assigned_count
          FROM assignment
          GROUP BY schedule_run_id, shift_id
        )
        SELECT
          sr.id AS schedule_run_id,
          COUNT(s.id) AS total_shifts,
          SUM(CASE WHEN COALESCE(a.assigned_count, 0) < s.required_staff THEN 1 ELSE 0 END) AS understaffed_shifts,
          sr.overall_score AS overall_score
        FROM schedulerun sr
        JOIN shift s
          ON s.date BETWEEN sr.week_start_date AND date(sr.week_start_date, '+13 day')
        LEFT JOIN assigned a
          ON a.schedule_run_id = sr.id AND a.shift_id = s.id
        WHERE sr.week_start_date BETWEEN :start AND :end
          AND sr.mode = :mode
        GROUP BY sr.id
        """
    )

    rows = session.exec(
        understaff_sql.params(start=start_d, end=end_d, mode=mode)
    ).all()
    if not rows:
        return {
            "mode": mode,
            "runs": 0,
            "avg_coverage_percent": 0.0,
            "avg_overall_fairness_percent": 0.0,
        }

    coverages = []
    fairness = []
    for r in rows:
        total = float(r.total_shifts or 0)
        under = float(r.understaffed_shifts or 0)
        coverage = 100.0 if total == 0 else 100.0 * (total - under) / total
        coverages.append(coverage)
        fairness.append(float(r.overall_score or 0.0))

    return {
        "mode": mode,
        "runs": len(rows),
        "avg_coverage_percent": round(sum(coverages) / len(coverages), 2),
        "avg_overall_fairness_percent": round(sum(fairness) / len(fairness), 2),
    }


@router.get("/compare", response_model=dict)
def analytics_compare(
    start: str = Query(..., description="ISO date, inclusive (period start)"),
    end: str = Query(..., description="ISO date, inclusive (period start)"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    start_d = _parse_date(start)
    end_d = _parse_date(end)

    baseline = analytics_summary(start, end, "baseline", session)
    optimized = analytics_summary(start, end, "optimized", session)

    def pct_change(new: float, old: float) -> float:
        if old == 0:
            return 0.0
        return 100.0 * (new - old) / old

    return {
        "range": {"start": start, "end": end},
        "baseline": baseline,
        "optimized": optimized,
        "delta_percent": {
            "coverage": round(
                pct_change(optimized["avg_coverage_percent"], baseline["avg_coverage_percent"]), 2
            ),
            "overall_fairness": round(
                pct_change(
                    optimized["avg_overall_fairness_percent"], baseline["avg_overall_fairness_percent"]
                ),
                2,
            ),
        },
    }

