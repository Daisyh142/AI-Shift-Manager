from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class HierarchyGraph:
    """
    Directed graph for hierarchy.

    Edge direction: higher_priority -> lower_priority
    Example: manager -> shift_lead -> regular

    We use DFS (with memoization) to compute a stable numeric rank:
    - leaf nodes (lowest) get rank 1
    - parents get rank = 1 + max(child ranks)
    Higher rank => higher priority.
    """

    edges: Dict[str, List[str]]

    @classmethod
    def from_edges(cls, edges: Iterable[tuple[str, str]]) -> "HierarchyGraph":
        adj: Dict[str, List[str]] = {}
        nodes: set[str] = set()
        for higher, lower in edges:
            nodes.add(higher)
            nodes.add(lower)
            adj.setdefault(higher, []).append(lower)
            adj.setdefault(lower, [])

        # Sort children to keep DFS deterministic.
        for k in adj:
            adj[k] = sorted(adj[k])
        return cls(edges=adj)

    def rank(self, node: str) -> int:
        @lru_cache(maxsize=None)
        def dfs(n: str) -> int:
            children = self.edges.get(n, [])
            if not children:
                return 1
            return 1 + max(dfs(c) for c in children)

        return dfs(node)


# Default hierarchies (your current business rules)
ROLE_HIERARCHY = HierarchyGraph.from_edges(
    [
        ("manager", "shift_lead"),
        ("shift_lead", "regular"),
    ]
)

EMPLOYMENT_TYPE_HIERARCHY = HierarchyGraph.from_edges(
    [
        ("full_time", "part_time"),
    ]
)


def employee_priority_score(*, role: str, employment_type: str) -> int:
    """
    Combines multiple hierarchies into a single sortable score.

    Connection to the rest of the app:
    - Scheduler uses this to allocate hours by priority.
    - Time-off approval uses this to choose which requests fit under capacity.
    - Later, Gemini prompts can include this score to reduce model \"memory\" load.
    """
    role_score = ROLE_HIERARCHY.rank(role)
    type_score = EMPLOYMENT_TYPE_HIERARCHY.rank(employment_type)

    # Weight role much higher so it always dominates employment type.
    return role_score * 100 + type_score

