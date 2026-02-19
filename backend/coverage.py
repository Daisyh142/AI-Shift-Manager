from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, Set

from sqlmodel import Session, delete, select

from .models import JobRole, JobRoleCanCover, JobRoleCoverClosure


def recompute_job_role_closure(session: Session) -> int:
    """
    Computes and stores the transitive closure of job-role coverage.

    We store, for each required_role, the set of role_names that can cover it.

    Why this exists (connection to scheduling):
    - Scheduling does eligibility checks constantly.
    - Instead of doing DFS every time, we do DFS once here and store results in SQL.
    - Then eligibility becomes a constant-time set membership check.
    """
    roles = [r.name for r in session.exec(select(JobRole)).all()]

    # Reverse adjacency: required_role -> roles that can cover it directly
    reverse_adj: Dict[str, list[str]] = defaultdict(list)
    for edge in session.exec(select(JobRoleCanCover)).all():
        reverse_adj[edge.to_role].append(edge.from_role)

    for r in roles:
        reverse_adj.setdefault(r, [])
        reverse_adj[r] = sorted(set(reverse_adj[r]))

    def dfs(start: str, seen: Set[str]) -> None:
        for parent in reverse_adj.get(start, []):
            if parent in seen:
                continue
            seen.add(parent)
            dfs(parent, seen)

    # Reset closure table and repopulate deterministically.
    session.exec(delete(JobRoleCoverClosure))
    now = datetime.utcnow()

    for required in sorted(roles):
        seen: Set[str] = {required}  # a role always covers itself
        dfs(required, seen)
        session.add(
            JobRoleCoverClosure(
                required_role=required,
                covers_json=json.dumps(sorted(seen)),
                computed_at=now,
            )
        )

    session.commit()
    return len(roles)


def cover_set_for_required_role(session: Session, required_role: str) -> set[str]:
    """
    Load the cached cover set for a required role.
    If missing (fresh DB), recompute once.
    """
    row = session.get(JobRoleCoverClosure, required_role)
    if not row:
        recompute_job_role_closure(session)
        row = session.get(JobRoleCoverClosure, required_role)
    if not row:
        return {required_role}
    try:
        return set(json.loads(row.covers_json))
    except json.JSONDecodeError:
        return {required_role}

