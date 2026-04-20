from __future__ import annotations

import argparse
import random
from datetime import UTC, date, datetime, time, timedelta

from sqlmodel import Session, delete, select

from .coverage import recompute_job_role_closure
from .db import engine, init_db
from .models import (
    Availability,
    Employee,
    EmployeeJobRole,
    JobRole,
    JobRoleCanCover,
    ScheduleRun,
    Shift,
    TimeOffRequest,
)
from .routers.time_off import approve_time_off
from .services.scheduling_service import generate_and_persist_schedule


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def reset_db(session: Session) -> None:
    session.exec(delete(TimeOffRequest))
    session.exec(delete(Availability))
    session.exec(delete(EmployeeJobRole))
    session.exec(delete(Employee))
    session.exec(delete(JobRoleCanCover))
    session.exec(delete(JobRole))
    session.exec(delete(Shift))
    session.exec(delete(ScheduleRun))
    session.commit()


def seed_roles_and_coverage(session: Session) -> None:
    roles = ["cashier", "barista", "server_lead", "prep_cook", "line_cook", "head_cook"]
    for r in roles:
        if not session.get(JobRole, r):
            session.add(JobRole(name=r))

    edges = [
        ("barista", "cashier"),
        ("server_lead", "cashier"),
        ("server_lead", "barista"),
        ("head_cook", "line_cook"),
        ("line_cook", "prep_cook"),
    ]
    for frm, to in edges:
        session.add(JobRoleCanCover(from_role=frm, to_role=to))
    session.commit()
    recompute_job_role_closure(session)


def seed_employees(session: Session, rng: random.Random, n_servers: int, n_cooks: int) -> None:
    employees: list[Employee] = []

    employees.append(
        Employee(
            id="mgr1",
            name="Manager One",
            max_weekly_hours=45,
            required_weekly_hours=40,
            role="manager",
            employment_type="full_time",
            category="server",
            pto_balance_hours=24,
        )
    )
    employees.append(
        Employee(
            id="lead1",
            name="Lead One",
            max_weekly_hours=40,
            required_weekly_hours=35,
            role="shift_lead",
            employment_type="full_time",
            category="server",
            pto_balance_hours=16,
        )
    )

    for i in range(n_servers):
        employees.append(
            Employee(
                id=f"sv{i+1}",
                name=f"Server {i+1}",
                max_weekly_hours=30,
                required_weekly_hours=rng.choice([20, 25, 30]),
                role="regular",
                employment_type=rng.choice(["part_time", "full_time"]),
                category="server",
                pto_balance_hours=rng.choice([0, 8, 16]),
            )
        )

    for i in range(n_cooks):
        employees.append(
            Employee(
                id=f"ck{i+1}",
                name=f"Cook {i+1}",
                max_weekly_hours=40,
                required_weekly_hours=rng.choice([30, 35, 40]),
                role="regular",
                employment_type="full_time",
                category="cook",
                pto_balance_hours=rng.choice([0, 8, 16]),
            )
        )

    for e in employees:
        session.add(e)
    session.commit()

    for e in employees:
        if e.category == "server":
            role_name = rng.choice(["cashier", "barista", "server_lead"])
        else:
            role_name = rng.choice(["prep_cook", "line_cook", "head_cook"])
        session.add(EmployeeJobRole(employee_id=e.id, role_name=role_name))
    session.commit()

    for e in employees:
        unavailable_days = set(rng.sample([0, 1, 2, 3, 4], k=rng.choice([0, 1, 2])))
        for dow in range(7):
            if dow in unavailable_days:
                continue
            session.add(
                Availability(
                    employee_id=e.id,
                    day_of_week=dow,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                )
            )
    session.commit()


def seed_shifts_for_period(session: Session, period_start: date) -> None:
    period_end = period_start + timedelta(days=13)
    current = period_start
    flex_templates = [(10, 18), (11, 19), (12, 20), (15, 21), (16, 20), (17, 23)]
    day_index = 0
    while current <= period_end:
        flex_start, flex_end = flex_templates[day_index % len(flex_templates)]
        templates = [
            (f"sv_open_{current.isoformat()}", "server", "cashier", 2, time(9, 0), time(17, 0)),
            (f"sv_close_{current.isoformat()}", "server", "cashier", 2, time(15, 0), time(23, 0)),
            (f"sv_flex_{current.isoformat()}", "server", "cashier", 1, time(flex_start, 0), time(flex_end, 0)),
            (f"ck_open_{current.isoformat()}", "cook", "prep_cook", 1, time(9, 0), time(17, 0)),
            (f"ck_close_{current.isoformat()}", "cook", "prep_cook", 1, time(15, 0), time(23, 0)),
            (f"ck_flex_{current.isoformat()}", "cook", "prep_cook", 1, time(flex_start, 0), time(flex_end, 0)),
        ]
        for shift_id, category, role, required_staff, start_time, end_time in templates:
            session.add(
                Shift(
                    id=shift_id,
                    date=current,
                    start_time=start_time,
                    end_time=end_time,
                    required_staff=required_staff,
                    required_category=category,
                    required_role=role,
                )
            )
        current += timedelta(days=1)
        day_index += 1
    session.commit()


def seed_time_off_for_period(session: Session, rng: random.Random, period_start: date) -> None:
    employees = session.exec(select(Employee)).all()
    period_end = period_start + timedelta(days=13)

    num_requests = rng.randint(3, 6)
    for _ in range(num_requests):
        e = rng.choice(employees)
        request_date = period_start + timedelta(days=rng.randint(0, 13))
        kind = rng.choice(["request_off", "pto"])
        hours = 8.0 if kind == "pto" else 0.0

        row = TimeOffRequest(
            employee_id=e.id,
            date=request_date,
            kind=kind,
            status="pending",
            hours=hours,
            reason="simulated_request",
            submitted_at=datetime.now(UTC) - timedelta(days=30),
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        try:
            approve_time_off(row.id, session)
        except Exception:
            pass

    session.exec(
        delete(TimeOffRequest).where(
            (TimeOffRequest.date < period_start) | (TimeOffRequest.date > period_end)
        )
    )
    session.commit()


def run_simulation(*, weeks: int, seed: int, reset: bool) -> None:
    init_db()
    rng = random.Random(seed)

    with Session(engine) as session:
        if reset:
            reset_db(session)

        seed_roles_and_coverage(session)
        seed_employees(session, rng, n_servers=8, n_cooks=4)

        start = _next_monday(date.today())
        for i in range(weeks):
            period_start = start + timedelta(days=14 * i)
            seed_shifts_for_period(session, period_start)
            seed_time_off_for_period(session, rng, period_start)

            generate_and_persist_schedule(session=session, week_start_date=period_start, mode="baseline")
            generate_and_persist_schedule(session=session, week_start_date=period_start, mode="optimized")

    print(f"Simulation complete: {weeks} period(s) starting {start.isoformat()}.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=12, help="Number of 2-week periods to simulate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible simulations.")
    parser.add_argument("--no-reset", action="store_true", help="Do not clear existing data first.")
    args = parser.parse_args()
    run_simulation(weeks=args.weeks, seed=args.seed, reset=not args.no_reset)


if __name__ == "__main__":
    main()

