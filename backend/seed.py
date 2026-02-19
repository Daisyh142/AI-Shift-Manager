from __future__ import annotations

from datetime import date, time, timedelta

from sqlmodel import Session

from .coverage import recompute_job_role_closure
from .db import engine, init_db
from .models import (
    Availability,
    Employee,
    EmployeeJobRole,
    JobRole,
    JobRoleCanCover,
    Shift,
)


def seed() -> None:
    """
    Seed a small deterministic dataset for Milestone 1 demos.

    Connection to the rest of the app:
    - Creates SQL rows used by the scheduler.
    - Recomputes the role coverage closure so eligibility checks are fast.
    """
    init_db()

    today = date.today()
    start = today - timedelta(days=today.weekday())  # current Monday
    end = start + timedelta(days=13)

    with Session(engine) as s:
        # Job roles (skills)
        roles = ["cashier", "barista", "server_lead", "prep_cook", "line_cook", "head_cook"]
        for r in roles:
            if not s.get(JobRole, r):
                s.add(JobRole(name=r))

        # Coverage edges (who can cover what)
        s.add(JobRoleCanCover(from_role="barista", to_role="cashier"))
        s.add(JobRoleCanCover(from_role="server_lead", to_role="cashier"))
        s.add(JobRoleCanCover(from_role="server_lead", to_role="barista"))
        s.add(JobRoleCanCover(from_role="head_cook", to_role="line_cook"))
        s.add(JobRoleCanCover(from_role="line_cook", to_role="prep_cook"))

        # Employees (position hierarchy + category)
        employees = [
            Employee(
                id="m1",
                name="Mona Manager",
                max_weekly_hours=45,
                required_weekly_hours=40,
                role="manager",
                employment_type="full_time",
                category="server",
                pto_balance_hours=16,
            ),
            Employee(
                id="l1",
                name="Sam ShiftLead",
                max_weekly_hours=40,
                required_weekly_hours=35,
                role="shift_lead",
                employment_type="full_time",
                category="server",
                pto_balance_hours=8,
            ),
            Employee(
                id="s1",
                name="Riley Server",
                max_weekly_hours=30,
                required_weekly_hours=25,
                role="regular",
                employment_type="part_time",
                category="server",
                pto_balance_hours=0,
            ),
            Employee(
                id="c1",
                name="Casey Cook",
                max_weekly_hours=40,
                required_weekly_hours=35,
                role="regular",
                employment_type="full_time",
                category="cook",
                pto_balance_hours=8,
            ),
            Employee(
                id="c2",
                name="Jordan Cook",
                max_weekly_hours=40,
                required_weekly_hours=35,
                role="regular",
                employment_type="full_time",
                category="cook",
                pto_balance_hours=0,
            ),
        ]
        for e in employees:
            if not s.get(Employee, e.id):
                s.add(e)

        # Employee job roles
        job_roles = [
            ("m1", "server_lead"),
            ("l1", "server_lead"),
            ("s1", "cashier"),
            ("c1", "line_cook"),
            ("c2", "prep_cook"),
        ]
        for emp_id, role_name in job_roles:
            s.add(EmployeeJobRole(employee_id=emp_id, role_name=role_name))

        # Availability (Mon–Sun 9–17 for everyone)
        for e in employees:
            for dow in range(7):
                s.add(
                    Availability(
                        employee_id=e.id,
                        day_of_week=dow,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                    )
                )

        # 2 weeks of shifts
        current = start
        shift_id = 1
        while current <= end:
            # Server shift: needs 2 people, cashier role
            s.add(
                Shift(
                    id=f"sv_{shift_id}",
                    date=current,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                    required_staff=2,
                    required_category="server",
                    required_role="cashier",
                )
            )
            shift_id += 1

            # Cook shift: needs 1 person, prep_cook role
            s.add(
                Shift(
                    id=f"ck_{shift_id}",
                    date=current,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                    required_staff=1,
                    required_category="cook",
                    required_role="prep_cook",
                )
            )
            shift_id += 1

            current = current + timedelta(days=1)

        s.commit()

        # Precompute role coverage closure
        recompute_job_role_closure(s)


if __name__ == "__main__":
    seed()
    print("Seed complete.")

