"""Pure-Python union-find behaviour -- no database needed."""

from __future__ import annotations

from lge.resolve.unionfind import UnionFind


def test_union_merges_and_find_agrees():
    uf = UnionFind([1, 2, 3, 4])
    uf.union(1, 2, "R1")
    uf.union(3, 4, "R1")
    assert uf.find(1) == uf.find(2)
    assert uf.find(3) == uf.find(4)
    assert uf.find(1) != uf.find(3)


def test_union_is_transitive():
    uf = UnionFind([1, 2, 3])
    uf.union(1, 2, "R1")
    uf.union(2, 3, "R2")
    assert uf.find(1) == uf.find(3)


def test_reunion_is_a_no_op():
    uf = UnionFind([1, 2])
    assert uf.union(1, 2, "R1") is True
    assert uf.union(1, 2, "R1") is False
    assert len(uf.edges) == 1


def test_components_groups_every_id():
    uf = UnionFind([1, 2, 3, 4, 5])
    uf.union(1, 2, "R1")
    uf.union(2, 3, "R1")
    groups = uf.components()
    sizes = sorted(len(members) for members in groups.values())
    assert sizes == [1, 1, 3]


def test_singleton_has_no_edges():
    uf = UnionFind([1])
    assert uf.edges == []
    assert uf.components() == {1: [1]}
