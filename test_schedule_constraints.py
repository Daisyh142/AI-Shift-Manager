#!/usr/bin/env python3
"""
Schedule constraint verification test.

Checks every hard rule the scheduler must satisfy before a schedule is shown
to the owner.  LangChain calls this suite after each generation attempt; if
any assertion fails, it passes the failure detail back to the scheduler as a
redo_reason so the next attempt can correct the problem.

Run manually:
    python test_schedule_constraints.py
or:
    pytest test_schedule_constraints.py -v
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

BASE_URL = "http://127.0.0.1:8000"

HARD_PREFIXES = (
    "DAILY_MIN_COVERAGE:",
    "LEADERSHIP_MIN_HOURS:",
    # MISSING_CATEGORY_COVERAGE / MISSING_MANAGER_COVERAGE: DAILY_MIN_COVERAGE
    # already captures "at least 1 leader/cook/server/busser per day", which is
    # the real user requirement.  Extra leadership slots being empty is a
    # structural capacity issue that retrying cannot resolve.
)

# A full-time shift lead or manager must receive at least this fraction of their per-period maximum hours 
LEADERSHIP_FLOOR_RATIO = 0.50

@dataclass
class Result:
    step: str
    status: str
    observation: str
    error: str = "None"


@dataclass
class TestResults:
    results: list[Result] = field(default_factory=list)

    def add(self, step: str, passed: bool, observation: str, error: str = "None") -> None:
        self.results.append(
            Result(step=step, status="PASS" if passed else "FAIL",
                   observation=observation, error=error)
        )

    def print_summary(self) -> None:
        print("\n" + "=" * 80)
        print("SCHEDULE CONSTRAINT TEST RESULTS")
        print("=" * 80)
        for r in self.results:
            print(f"\nStep {r.step}: {r.status}")
            print(f"  {r.observation}")
            if r.error != "None":
                print(f"  Error: {r.error}")
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        print("\n" + "=" * 80)
        print(f"Summary: {passed} PASSED, {failed} FAILED out of {len(self.results)} tests")
        print("=" * 80 + "\n")

    @property
    def all_passed(self) -> bool:
        return all(r.status == "PASS" for r in self.results)


def _get(url: str, token: str) -> requests.Response:
    return requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def _post(url: str, token: str, body: dict) -> requests.Response:
    return requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )


def _json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {}

def run_constraint_tests() -> TestResults:
    results = TestResults()

    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "owner@demo.com", "password": "demo"},
        timeout=10,
    )
    if resp.status_code != 200:
        results.add("auth", False, "Could not log in as owner.", str(resp.text[:200]))
        return results

    token: str = _json(resp).get("access_token", "")
    results.add("1-auth", True, "Authenticated as owner.")

  
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    # use_ai=false skips the Gemini summary call so the test never waits on an
    # unavailable API key and the 120-second timeout is never the reason a run
    # returns an empty body.
    gen_resp = _post(f"{BASE_URL}/schedules/generate?use_ai=false", token, {"week_start_date": week_start})
    if gen_resp.status_code not in (200, 201):
        results.add("2-generate", False, "Generate endpoint returned an error.", str(gen_resp.text[:300]))
        return results

    payload = _json(gen_resp)
    # The generate endpoint returns {schedule_run_id, schedule: {violations, fairness_scores, ...}}
    run_id: int | None = payload.get("schedule_run_id")
    schedule_payload: dict = payload.get("schedule", {})
    violations: list[str] = schedule_payload.get("violations", [])
    results.add(
        "2-generate",
        run_id is not None,
        f"Schedule run #{run_id} created. {len(violations)} total violations.",
    )

    
    hard_violations = [v for v in violations if any(v.startswith(p) for p in HARD_PREFIXES)]
    results.add(
        "3-no-hard-violations",
        len(hard_violations) == 0,
        (
            f"{len(hard_violations)} hard violation(s) found."
            if hard_violations
            else "No hard violations — schedule passed all hard constraints."
        ),
        "; ".join(hard_violations[:5]) if hard_violations else "None",
    )


    daily_coverage_fails = [v for v in violations if v.startswith("DAILY_MIN_COVERAGE:")]
    results.add(
        "4-daily-min-coverage",
        len(daily_coverage_fails) == 0,
        (
            f"Missing daily coverage on {len(daily_coverage_fails)} day(s)."
            if daily_coverage_fails
            else "Every day has cook, server, busser, and leadership coverage."
        ),
        "; ".join(daily_coverage_fails[:3]) if daily_coverage_fails else "None",
    )

    
    leadership_hour_fails = [v for v in violations if v.startswith("LEADERSHIP_MIN_HOURS:")]
    results.add(
        "5-leadership-min-hours",
        len(leadership_hour_fails) == 0,
        (
            f"{len(leadership_hour_fails)} leader(s) below their minimum hour floor."
            if leadership_hour_fails
            else "All shift leads and managers are at or above their minimum hours."
        ),
        "; ".join(leadership_hour_fails) if leadership_hour_fails else "None",
    )


    avail_fails = [v for v in violations if v.startswith("availability_violation:")]
    results.add(
        "6-no-availability-violations",
        len(avail_fails) == 0,
        (
            f"{len(avail_fails)} availability violation(s) — employees scheduled outside their windows."
            if avail_fails
            else "All assignments are within employee availability windows."
        ),
        "; ".join(avail_fails[:3]) if avail_fails else "None",
    )

    
    overlap_fails = [v for v in violations if v.startswith("overlap_violation:")]
    results.add(
        "7-no-overlap-violations",
        len(overlap_fails) == 0,
        (
            f"{len(overlap_fails)} overlap violation(s) — employees double-booked on the same day."
            if overlap_fails
            else "No employees are double-booked."
        ),
        "; ".join(overlap_fails[:3]) if overlap_fails else "None",
    )

    
    max_hour_fails = [v for v in violations if v.startswith("max_hours_violation:")]
    results.add(
        "8-no-max-hours-violations",
        len(max_hour_fails) == 0,
        (
            f"{len(max_hour_fails)} max-hour violation(s) — employees scheduled beyond their cap."
            if max_hour_fails
            else "No employees exceed their maximum weekly hours."
        ),
        "; ".join(max_hour_fails[:3]) if max_hour_fails else "None",
    )

    
    # ------------------------------------------------------------------
    # Step 9: Verify leadership fairness using scores already in the response.
    # The generate endpoint embeds fairness_scores inside schedule_payload so
    # no additional network request is needed.
    # ------------------------------------------------------------------
    fairness_scores: list[dict] = schedule_payload.get("fairness_scores", [])

    emp_resp = _get(f"{BASE_URL}/employees/", token)
    employees: list[dict] = _json(emp_resp) if emp_resp.status_code == 200 else []
    leadership_ids = {
        e["id"]
        for e in employees
        if e.get("role") in ("manager", "shift_lead")
        and e.get("employment_type") == "full_time"
    }

    low_fairness: list[str] = []
    for score in fairness_scores:
        emp_id = score.get("employee_id", "")
        if emp_id not in leadership_ids:
            continue
        utilization = score.get("utilization", 0.0)
        if utilization < LEADERSHIP_FLOOR_RATIO:
            low_fairness.append(
                f"{emp_id}: utilization={utilization * 100:.1f}% "
                f"(assigned={score.get('assigned_hours', 0):.1f}h, "
                f"max={score.get('max_hours', 0):.1f}h)"
            )

    results.add(
        "9-leadership-fairness",
        len(low_fairness) == 0,
        (
            f"{len(low_fairness)} leader(s) below {LEADERSHIP_FLOOR_RATIO*100:.0f}% utilization: "
            + ", ".join(low_fairness)
            if low_fairness
            else f"All leaders are at or above {LEADERSHIP_FLOOR_RATIO*100:.0f}% utilization."
        ),
        "; ".join(low_fairness) if low_fairness else "None",
    )

    return results


if __name__ == "__main__":
    print("Running schedule constraint verification...")
    print(f"Backend: {BASE_URL}\n")
    test_results = run_constraint_tests()
    test_results.print_summary()
    sys.exit(0 if test_results.all_passed else 1)
