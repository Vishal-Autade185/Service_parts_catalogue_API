"""PRODUCT.md 12.4: graph, cycle removal, totals, paths and statuses."""
from __future__ import annotations

import math

import pytest

from app.catalogue import find_first_back_edge, reachable, remove_cycles
from tests.conftest import build, make_data


def graph(edge_list, qty=1):
    g = {}
    for p, c in edge_list:
        g.setdefault(p, {})[c] = qty
    return g


def run_removal(edge_list, root="R"):
    """Remove cycles and check the 8.3 properties; return the removed (parent, child) pairs."""
    g = graph(edge_list)
    original = {p: dict(cs) for p, cs in g.items()}
    before = reachable(g, root)
    removed = remove_cycles(g, root)
    pairs = [(p, c) for p, c, _ in removed]
    assert find_first_back_edge(g, root) is None                      # acyclic
    assert reachable(g, root) == before                               # nobody dropped out
    assert len(set(pairs)) == len(pairs)                              # each edge once
    for p, c in pairs:                                                # only cycle edges removed
        assert p in reachable(original, c)
    return pairs


@pytest.mark.parametrize(
    "edges, n_removed",
    [
        ([("R", "A"), ("A", "B"), ("B", "A")], 1),                                      # direct
        ([("R", "A"), ("A", "B"), ("B", "C"), ("C", "A")], 1),                          # indirect
        ([("R", "A"), ("R", "B"), ("A", "C"), ("B", "C"), ("C", "D"), ("D", "C")], 1),  # via two parents
        ([("R", "A"), ("A", "B"), ("B", "A"), ("R", "C"), ("C", "D"), ("D", "C")], 2),  # several cycles
        ([("R", "A"), ("A", "B"), ("B", "R")], 1),                                      # touches the root
    ],
)
def test_cycle_shapes(edges, n_removed):
    assert len(run_removal(edges)) == n_removed


def test_shared_part_outside_cycle_untouched():
    pairs = run_removal([("R", "A"), ("R", "B"), ("A", "S"), ("B", "S"), ("A", "C"), ("C", "A")])
    assert ("A", "S") not in pairs and ("B", "S") not in pairs


APPENDIX_Q = [("AS-1", "AS-2"), ("AS-1", "FA-9"), ("AS-2", "FA-9"), ("AS-2", "EL-5")]


@pytest.mark.parametrize(
    "root, edges, expected",
    [
        # fastener entered first
        ("R", [("R", "A"), ("R", "X"), ("A", "F"), ("A", "Q"), ("X", "Y"), ("X", "Z"),
               ("Y", "F"), ("Y", "W"), ("F", "X")], ("F", "X")),
        # single-child assembly on the cycle
        ("R", [("R", "A"), ("R", "B"), ("A", "M"), ("M", "F"), ("B", "F"), ("F", "A")], ("F", "A")),
        # guard: the cut would drop parts
        ("R", [("R", "U"), ("U", "V"), ("V", "U"), ("V", "X")], ("V", "U")),
        # Appendix Q plus a bad edge
        ("AS-1", APPENDIX_Q + [("FA-9", "AS-2")], ("FA-9", "AS-2")),
        # two real assemblies list each other (ambiguous): plain DFS back edge
        ("R", [("R", "A"), ("R", "B"), ("A", "B"), ("A", "P"), ("B", "A"), ("B", "Q")], ("B", "A")),
    ],
    ids=["fastener-first", "single-child-assembly", "guard", "appendix-q-bad-edge", "two-real-assemblies"],
)
def test_cycle_rule_cases(root, edges, expected):
    assert run_removal(edges, root) == [expected]


def test_guard_keeps_parts_in_machine(tmp_path):
    cat = build(make_data(tmp_path, [("R", "U", 1), ("U", "V", 1), ("V", "U", 1), ("V", "X", 1)]), "R")
    assert set(cat.part_info) == {"R", "U", "V", "X"}


def test_removed_edges_on_catalogue(tmp_path, caplog):
    d = make_data(tmp_path, [("R", "A", 1), ("A", "B", 2), ("B", "A", 5)])
    with caplog.at_level("WARNING", logger="app"):
        cat = build(d, "R")
    assert cat.removed_edges == [("B", "A", 5)]
    assert "cycle edge removed: B -> A x5 (back_edge)" in caplog.text
    assert cat.part_info["A"]["parents"] == ["R"]
    assert cat.part_info["B"]["total_quantity"] == 2


def test_orphan_assembly_excluded(tmp_path):
    cat = build(make_data(tmp_path, [("R", "A", 2), ("A", "X", 3), ("O", "X", 7), ("O", "Y", 1)]), "R")
    assert set(cat.part_info) == {"R", "A", "X"}
    assert cat.part_info["X"]["parents"] == ["A"]
    assert cat.part_info["X"]["total_quantity"] == 6
    assert cat.paths("X") == [["R", "A", "X"]]


def test_root_absent_from_bom(tmp_path):
    cat = build(make_data(tmp_path, [("A", "B", 1)], [("R", "A", "Root")], [("R", "Y", "", "")]), "R")
    assert list(cat.part_info) == ["R"]
    assert cat.part_info["R"]["total_quantity"] == 1
    assert cat.part_info["R"]["status"] == "ready"
    assert cat.paths("R") == [["R"]]
    assert cat.counts == {"parts": 1, "ready": 1, "missing": 0, "not_replaceable": 0}


def test_root_name_is_normalised(tmp_path):
    cat = build(make_data(tmp_path, [("AS-1", "FA-9", 2)]), " as-1 ")
    assert cat.root == "AS-1"
    assert cat.part_info["FA-9"]["total_quantity"] == 2


def test_total_sums_over_every_path(tmp_path):
    bom = [("R", "A", 2), ("R", "B", 3), ("A", "C", 5), ("B", "C", 7), ("C", "D", 11)]
    cat = build(make_data(tmp_path, bom), "R")
    assert cat.part_info["C"]["total_quantity"] == 2 * 5 + 3 * 7
    assert cat.part_info["D"]["total_quantity"] == (2 * 5 + 3 * 7) * 11
    assert cat.paths("D") == [["R", "A", "C", "D"], ["R", "B", "C", "D"]]
    assert cat.part_info["C"]["children"] == [{"part_number": "D", "quantity": 11}]


def test_statuses_and_serials(tmp_path):
    bom = [("R", "A", 1), ("R", "B", 1), ("R", "C", 1), ("R", "D", 1)]
    master = [("R", "A", "root"), ("A", "A", "a"), ("B", "A", "b"), ("C", "A", "c")]
    service = [("A", "Y", "100", "200"), ("B", "Y", "150", ""), ("C", "N", "", ""), ("D", "Y", "", "")]
    cat = build(make_data(tmp_path, bom, master, service), "R")
    assert {pn: i["status"] for pn, i in cat.part_info.items()} == {
        "R": "not_replaceable", "A": "ready", "B": "ready", "C": "not_replaceable", "D": "missing",
    }
    assert [cat.applicable(s) for s in (99, 100, 150, 200, 201)] == [0, 1, 2, 2, 1]


def test_deep_chain_no_recursion(tmp_path):
    n = 2000
    bom = [(f"P{i}", f"P{i + 1}", i % 3 + 1) for i in range(n)]
    cat = build(make_data(tmp_path, bom), "P0")
    assert cat.part_info[f"P{n}"]["total_quantity"] == math.prod(i % 3 + 1 for i in range(n))
    paths = cat.paths(f"P{n}")
    assert len(paths) == 1 and len(paths[0]) == n + 1
