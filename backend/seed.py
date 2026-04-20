from __future__ import annotations

from datetime import date, time, timedelta

from sqlmodel import Session

from .coverage import recompute_job_role_closure
from . import db
from .models import (
    Availability,
    Employee,
    EmployeeJobRole,
    JobRole,
    JobRoleCanCover,
    Shift,
)


def seed_shifts_for_period(s: Session, start: date) -> None:
    end = start + timedelta(days=13)
    close_templates = [(15, 23), (16, 23)]
    mid_templates = [(11, 19), (12, 20), (13, 21), (14, 19)]
    short_templates = [(16, 21), (16, 20), (17, 21), (18, 23)]
    non_lead_categories = ["server", "cook", "busser"]
    current = start
    while current <= end:
        day_idx = current.toordinal()
        close_s, close_e = close_templates[day_idx % len(close_templates)]
        mid_s, mid_e = mid_templates[day_idx % len(mid_templates)]
        short_a_s, short_a_e = short_templates[day_idx % len(short_templates)]
        short_b_s, short_b_e = short_templates[(day_idx + 1) % len(short_templates)]
        mid_category = non_lead_categories[day_idx % len(non_lead_categories)]
        short_category_a = non_lead_categories[(day_idx + 1) % len(non_lead_categories)]
        short_category_b = non_lead_categories[(day_idx + 2) % len(non_lead_categories)]
        role_templates = [
            ("server", "cashier", "sv"),
            ("cook", "prep_cook", "ck"),
            ("busser", "busser", "bs"),
        ]
        for category, required_role, prefix in role_templates:
            d = current.isoformat()
            is_sat_or_sun = current.weekday() >= 5
            daily_templates: list[tuple[str, time, time]] = [
                (f"{prefix}_open_{d}", time(9, 0), time(17, 0)),
                (f"{prefix}_close_{d}", time(close_s, 0), time(close_e, 0)),
            ]
            if is_sat_or_sun:
                daily_templates.append((f"{prefix}_pm_{d}", time(15, 0), time(23, 0)))
            for shift_id, block_start, block_end in daily_templates:
                if not s.get(Shift, shift_id):
                    s.add(Shift(
                        id=shift_id, date=current,
                        start_time=block_start, end_time=block_end,
                        required_staff=1, required_category=category, required_role=required_role,
                    ))
        d = current.isoformat()
        for shift_id, block_start, block_end, req_role in [
            (f"ld_mgr_open_{d}", time(9, 0), time(17, 0), "manager"),
            (f"ld_mgr_close_{d}", time(close_s, 0), time(close_e, 0), "manager"),
            (f"ld_lead_open_{d}", time(9, 0), time(17, 0), "server_lead"),
            (f"ld_lead_support_{d}", time(close_s, 0), time(close_e, 0), "server_lead"),
        ]:
            if not s.get(Shift, shift_id):
                s.add(Shift(
                    id=shift_id, date=current,
                    start_time=block_start, end_time=block_end,
                    required_staff=1, required_category="leadership", required_role=req_role,
                ))
        current = current + timedelta(days=1)


def seed() -> None:
    db.init_db()

    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=13)

    with Session(db.engine) as s:
        roles = ["cashier", "barista", "server_lead", "prep_cook", "line_cook", "head_cook", "busser"]
        for r in roles:
            if not s.get(JobRole, r):
                s.add(JobRole(name=r))

        s.add(JobRoleCanCover(from_role="barista", to_role="cashier"))
        s.add(JobRoleCanCover(from_role="server_lead", to_role="cashier"))
        s.add(JobRoleCanCover(from_role="server_lead", to_role="barista"))
        s.add(JobRoleCanCover(from_role="server_lead", to_role="busser"))
        s.add(JobRoleCanCover(from_role="head_cook", to_role="line_cook"))
        s.add(JobRoleCanCover(from_role="line_cook", to_role="prep_cook"))

        employees = [
            Employee(id="c1", name="Casey [Cook]", max_weekly_hours=40, required_weekly_hours=36, role="regular", employment_type="full_time", category="cook", active=True, pto_balance_hours=8),
            Employee(id="c2", name="Jordan [Cook]", max_weekly_hours=40, required_weekly_hours=36, role="regular", employment_type="full_time", category="cook", active=True, pto_balance_hours=8),
            Employee(id="c3", name="Rae [Cook]", max_weekly_hours=16, required_weekly_hours=12, role="regular", employment_type="part_time", category="cook", active=True, pto_balance_hours=8),
            Employee(id="c4", name="Drew [Cook]", max_weekly_hours=20, required_weekly_hours=16, role="regular", employment_type="part_time", category="cook", active=True, pto_balance_hours=8),
            Employee(id="s1", name="Riley [Server]", max_weekly_hours=40, required_weekly_hours=36, role="regular", employment_type="full_time", category="server", active=True, pto_balance_hours=0),
            Employee(id="s2", name="Taylor [Server]", max_weekly_hours=40, required_weekly_hours=34, role="regular", employment_type="full_time", category="server", active=True, pto_balance_hours=8),
            Employee(id="s3", name="Alex [Server]", max_weekly_hours=16, required_weekly_hours=12, role="regular", employment_type="part_time", category="server", active=True, pto_balance_hours=8),
            Employee(id="s4", name="Jamie [Server]", max_weekly_hours=20, required_weekly_hours=16, role="regular", employment_type="part_time", category="server", active=True, pto_balance_hours=8),
            Employee(id="b1", name="Quinn [Busser]", max_weekly_hours=40, required_weekly_hours=36, role="regular", employment_type="full_time", category="busser", active=True, pto_balance_hours=8),
            Employee(id="b2", name="Rowan [Busser]", max_weekly_hours=40, required_weekly_hours=36, role="regular", employment_type="full_time", category="busser", active=True, pto_balance_hours=8),
            Employee(id="b3", name="Kai [Busser]", max_weekly_hours=20, required_weekly_hours=16, role="regular", employment_type="part_time", category="busser", active=True, pto_balance_hours=8),
            Employee(id="b4", name="Reese [Busser]", max_weekly_hours=16, required_weekly_hours=12, role="regular", employment_type="part_time", category="busser", active=True, pto_balance_hours=8),
            Employee(id="m1", name="Mona [Manager]", max_weekly_hours=56, required_weekly_hours=50, role="manager", employment_type="full_time", category="leadership", active=True, pto_balance_hours=16),
            Employee(id="m2", name="Sam [Manager]", max_weekly_hours=56, required_weekly_hours=50, role="manager", employment_type="full_time", category="leadership", active=True, pto_balance_hours=16),
            Employee(id="l1", name="Lane [Shift Lead]", max_weekly_hours=40, required_weekly_hours=34, role="shift_lead", employment_type="full_time", category="leadership", active=True, pto_balance_hours=8),
            Employee(id="l2", name="Sky [Shift Lead]", max_weekly_hours=40, required_weekly_hours=34, role="shift_lead", employment_type="full_time", category="leadership", active=True, pto_balance_hours=8),
        ]
        for e in employees:
            if not s.get(Employee, e.id):
                s.add(e)

        job_roles = [
            ("c1", "line_cook"),
            ("c2", "head_cook"),
            ("c3", "prep_cook"),
            ("c4", "prep_cook"),
            ("s1", "server_lead"),
            ("s2", "cashier"),
            ("s3", "barista"),
            ("s4", "cashier"),
            ("b1", "busser"),
            ("b2", "busser"),
            ("b3", "busser"),
            ("b4", "busser"),
            ("m1", "server_lead"),
            ("m2", "server_lead"),
            ("l1", "server_lead"),
            ("l2", "server_lead"),
        ]
        for emp_id, role_name in job_roles:
            s.add(EmployeeJobRole(employee_id=emp_id, role_name=role_name))

        availability_patterns = {
            "c1": [(0, 9, 18), (1, 9, 18), (2, 9, 18), (3, 9, 18), (4, 9, 18)],
            "c2": [(0, 15, 23), (2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23), (6, 15, 23)],
            "c3": [(4, 15, 23), (5, 9, 23), (6, 9, 23)],
            "c4": [(1, 16, 23), (2, 16, 23), (4, 16, 23), (5, 15, 23), (6, 15, 23)],
            "s1": [(0, 15, 23), (2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23), (6, 15, 23)],
            "s2": [(0, 9, 18), (1, 9, 18), (2, 9, 18), (3, 9, 18), (4, 9, 18), (5, 9, 17)],
            "s3": [(4, 15, 23), (5, 9, 23), (6, 9, 23)],
            "s4": [(1, 16, 23), (2, 16, 23), (4, 16, 23), (5, 15, 23), (6, 15, 23)],
            "b1": [(0, 9, 18), (1, 9, 18), (2, 9, 18), (3, 9, 18), (4, 9, 18)],
            "b2": [(0, 15, 23), (1, 15, 23), (2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23), (6, 15, 23)],
            "b3": [(2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23), (6, 15, 23)],
            "b4": [(5, 9, 17), (6, 9, 17)],
            "m1": [(0, 9, 17), (1, 9, 17), (2, 9, 17), (3, 9, 17), (4, 9, 17)],
            "m2": [(0, 15, 23), (1, 15, 23), (2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23)],
            "l1": [(2, 15, 23), (3, 15, 23), (4, 15, 23), (5, 15, 23), (6, 15, 23)],
            "l2": [(1, 9, 17), (2, 9, 17), (4, 9, 17), (5, 9, 17), (6, 9, 17)],
        }
        for employee_id, windows in availability_patterns.items():
            for dow, start_hour, end_hour in windows:
                s.add(
                    Availability(
                        employee_id=employee_id,
                        day_of_week=dow,
                        start_time=time(start_hour, 0),
                        end_time=time(end_hour, 0),
                    )
                )

        seed_shifts_for_period(s, start)
        s.commit()

        recompute_job_role_closure(s)


if __name__ == "__main__":
    seed()
    print("Seed complete.")

