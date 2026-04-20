from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class HierarchyGraph:
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
    role_score = ROLE_HIERARCHY.rank(role)
    type_score = EMPLOYMENT_TYPE_HIERARCHY.rank(employment_type)

    return role_score * 100 + type_score

