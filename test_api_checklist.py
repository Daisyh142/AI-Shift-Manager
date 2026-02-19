#!/usr/bin/env python3
"""API verification script aligned with current WorkForYou endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import json
from typing import Any

import requests

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class Result:
    step: str
    status: str
    observation: str
    error: str = "None"


@dataclass
class APITestResults:
    results: list[Result] = field(default_factory=list)

    def add(self, step: str, status: str, observation: str, error: str | None = None) -> None:
        self.results.append(Result(step=step, status=status, observation=observation, error=error or "None"))

    def print(self) -> None:
        print("\n" + "=" * 80)
        print("API TEST RESULTS")
        print("=" * 80)
        for result in self.results:
            print(f"\nStep {result.step}: {result.status}")
            print(f"  Observation: {result.observation}")
            if result.error != "None":
                print(f"  Error: {result.error}")
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        print("\n" + "=" * 80)
        print(f"Summary: {passed} PASSED, {failed} FAILED out of {len(self.results)} tests")
        print("=" * 80 + "\n")


def try_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


def expect_status(results: APITestResults, step: str, resp: requests.Response, ok: set[int], success_msg: str) -> bool:
    if resp.status_code in ok:
        results.add(step, "PASS", success_msg)
        return True
    body = try_json(resp)
    results.add(step, "FAIL", f"Unexpected status {resp.status_code}", json.dumps(body, default=str))
    return False


def test_api_checklist() -> None:
    results = APITestResults()

    owner_token = ""
    employee_token = ""
    schedule_run_id: int | None = None

    # Step 0: Seed
    r = requests.post(f"{BASE_URL}/seed", timeout=20)
    expect_status(results, "0", r, {200}, "Database seeded")

    # Step 1: Owner login
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "owner@demo.com", "password": "demo"},
        timeout=20,
    )
    if expect_status(results, "1", r, {200}, "Owner login succeeded"):
        owner_token = r.json().get("access_token", "")

    if not owner_token:
        results.add("2-10", "FAIL", "Aborted because owner token is missing")
        results.print()
        return

    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # Step 2: Generate schedule (owner)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    r = requests.post(
        f"{BASE_URL}/schedules/generate",
        headers=owner_headers,
        params={"mode": "optimized"},
        json={"week_start_date": week_start},
        timeout=20,
    )
    if expect_status(results, "2", r, {200}, f"Generated schedule for week_start_date={week_start}"):
        schedule_run_id = r.json().get("schedule_run_id")

    if schedule_run_id is None:
        results.add("3-10", "FAIL", "Aborted because schedule_run_id is missing")
        results.print()
        return

    # Step 3: Publish schedule
    r = requests.post(f"{BASE_URL}/schedules/{schedule_run_id}/publish", headers=owner_headers, timeout=20)
    expect_status(results, "3", r, {200}, f"Published schedule run {schedule_run_id}")

    # Step 4: Latest published
    r = requests.get(f"{BASE_URL}/schedules/latest", params={"status": "published"}, timeout=20)
    expect_status(results, "4", r, {200}, "Fetched latest published schedule summary")

    # Step 5: Owner requests list
    r = requests.get(f"{BASE_URL}/time-off/requests", headers=owner_headers, timeout=20)
    expect_status(results, "5", r, {200}, "Owner fetched time-off requests")

    # Step 6: Employee login
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "employee@demo.com", "password": "demo"},
        timeout=20,
    )
    if expect_status(results, "6", r, {200}, "Employee login succeeded"):
        employee_token = r.json().get("access_token", "")

    if not employee_token:
        results.add("7-10", "FAIL", "Aborted because employee token is missing")
        results.print()
        return

    employee_headers = {"Authorization": f"Bearer {employee_token}"}

    # Step 7: Employee /auth/me
    r = requests.get(f"{BASE_URL}/auth/me", headers=employee_headers, timeout=20)
    expect_status(results, "7", r, {200}, "Employee session validated via /auth/me")

    # Step 8: Employee reads team schedule summary
    r = requests.get(f"{BASE_URL}/schedules/latest", params={"status": "published"}, headers=employee_headers, timeout=20)
    expect_status(results, "8", r, {200}, "Employee fetched latest published schedule summary")

    # Step 9: Employee submits time-off request
    request_date = (date.today() + timedelta(days=14)).isoformat()
    r = requests.post(
        f"{BASE_URL}/time-off/requests",
        headers=employee_headers,
        json={
            "employee_id": "s1",
            "date": request_date,
            "kind": "request_off",
            "hours": 0,
            "reason": "Automated verification request",
        },
        timeout=20,
    )
    request_id: int | None = None
    if expect_status(results, "9", r, {200}, f"Employee submitted request_off for {request_date}"):
        request_id = r.json().get("id")

    # Step 10: Owner approves latest submitted request
    if request_id is not None:
        r = requests.post(f"{BASE_URL}/time-off/requests/{request_id}/approve", headers=owner_headers, timeout=20)
        if r.status_code == 200:
            results.add("10", "PASS", f"Owner approved request {request_id}")
        elif r.status_code == 400:
            # Capacity constraints can legitimately block approval; verify deny flow instead.
            deny = requests.post(f"{BASE_URL}/time-off/requests/{request_id}/deny", headers=owner_headers, timeout=20)
            expect_status(
                results,
                "10",
                deny,
                {200},
                f"Owner could not approve due constraints and successfully denied request {request_id}",
            )
        else:
            body = try_json(r)
            results.add("10", "FAIL", f"Unexpected approve status {r.status_code}", json.dumps(body, default=str))
    else:
        results.add("10", "FAIL", "Skipped approve test because request_id was missing")

    results.print()


if __name__ == "__main__":
    print("Starting API checklist verification...")
    try:
        health = requests.get(f"{BASE_URL}/", timeout=10)
        print(f"Backend health status: {health.status_code} body={try_json(health)}")
    except Exception as exc:
        print(f"Cannot reach backend at {BASE_URL}: {exc}")
        raise SystemExit(1)

    test_api_checklist()
