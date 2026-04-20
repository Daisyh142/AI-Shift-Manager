from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Set

from sqlmodel import Session, delete, select

from .models import JobRole, JobRoleCanCover, JobRoleCoverClosure

logger = logging.getLogger(__name__)


def recompute_job_role_closure(session: Session) -> int:
    roles = [r.name for r in session.exec(select(JobRole)).all()]

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

    session.exec(delete(JobRoleCoverClosure))
    now = datetime.now(timezone.utc)

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
    row = session.get(JobRoleCoverClosure, required_role)
    if not row:
        recompute_job_role_closure(session)
        row = session.get(JobRoleCoverClosure, required_role)
    if not row:
        return {required_role}
    try:
        return set(json.loads(row.covers_json))
    except json.JSONDecodeError:
        logger.exception("Invalid covers_json for required_role=%s", required_role)
        print(f"[coverage] Invalid closure JSON for required_role={required_role}; defaulting to self-cover set.")
        return {required_role}

