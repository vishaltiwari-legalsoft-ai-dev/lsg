"""Union-find (disjoint-set) over arbitrary hashable ids.

`resolve_identity` never enumerates pairs for R1/R2 -- it unions every
observation sharing a domain or phone directly -- and does exactly one
pairwise SQL pass each for R3/R4, inside blocks (addr_hash, zip5). This
module is the pure, DB-free merge structure both stages feed. It also
records every real merge as an edge, which is how identity.py later tags
each firm_alias row with the specific rule (R1/R2/R3) that justified it.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable


class UnionFind:
    """Path-compressed, union-by-size disjoint-set forest.

    `union(a, b, rule)` merges the sets containing `a` and `b` and appends
    `(a, b, rule)` to `.edges` iff that merge actually joined two previously
    distinct sets -- re-unioning two ids already together is a no-op and
    logs nothing, so `.edges` is exactly the (n - k) real merges for a
    forest that ends with k components over n ids.
    """

    def __init__(self, ids: Iterable[Hashable]) -> None:
        self._parent: dict[Hashable, Hashable] = {i: i for i in ids}
        self._size: dict[Hashable, int] = dict.fromkeys(self._parent, 1)
        self.edges: list[tuple[Hashable, Hashable, str]] = []

    def find(self, x: Hashable) -> Hashable:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: Hashable, b: Hashable, rule: str) -> bool:
        """Merge the sets containing `a` and `b`. Returns True iff a real
        merge happened (they were previously in different sets)."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        self.edges.append((a, b, rule))
        return True

    def components(self) -> dict[Hashable, list[Hashable]]:
        """root id -> every member id of that component (roots included)."""
        groups: dict[Hashable, list[Hashable]] = {}
        for x in self._parent:
            groups.setdefault(self.find(x), []).append(x)
        return groups
