"""PRODUCT.md 12.8: force each safety net and check the service still builds.
(The global exception handler test lives in test_api.py, Phase 7.)"""
from __future__ import annotations

import logging

import app.catalogue as catalogue
from app.catalogue import find_first_back_edge, remove_cycles, topo_order
from tests.conftest import build, make_data

CYCLIC = [("R", "A", 1), ("A", "B", 2), ("B", "C", 1), ("C", "A", 1), ("R", "D", 1), ("D", "E", 1), ("E", "D", 1)]


def graph(rows):
    g = {}
    for p, c, q in rows:
        g.setdefault(p, {})[c] = q
    return g


def test_choose_cut_raising_falls_back_to_back_edge(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("forced")
    monkeypatch.setattr(catalogue, "choose_cut", boom)
    g = graph(CYCLIC)
    with caplog.at_level(logging.WARNING, logger="app"):
        removed = remove_cycles(g, "R")
    assert [(p, c) for p, c, _ in removed] == [("C", "A"), ("E", "D")]   # plain DFS back edges
    assert find_first_back_edge(g, "R") is None
    assert "back_edge_after_error:RuntimeError('forced')" in caplog.text


def test_iteration_cap_fallback_leaves_dag(monkeypatch, caplog):
    monkeypatch.setattr(catalogue, "cycle_pass_cap", lambda g: 0)
    g = graph(CYCLIC)
    with caplog.at_level(logging.WARNING, logger="app"):
        removed = remove_cycles(g, "R")
    assert len(removed) == 2
    assert find_first_back_edge(g, "R") is None
    assert "iteration cap" in caplog.text
    assert "(fallback)" in caplog.text


def test_topo_order_reports_surviving_cycle():
    order, nodes = topo_order(graph(CYCLIC), "R")
    assert len(order) < len(nodes)


def test_surviving_cycle_still_builds_catalogue(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(catalogue, "remove_cycles", lambda g, root: [])   # let cycles reach topo_order
    with caplog.at_level(logging.WARNING, logger="app"):
        cat = build(make_data(tmp_path, CYCLIC), "R")
    assert "a cycle survived" in caplog.text
    assert set(cat.part_info) == {"R", "A", "B", "C", "D", "E"}
    assert sorted((p, c) for p, c, _ in cat.removed_edges) == [("C", "A"), ("E", "D")]
    assert cat.part_info["C"]["total_quantity"] == 2
    assert cat.paths("C") == [["R", "A", "B", "C"]]
    assert cat.counts["parts"] == 6


def test_cycle_surviving_every_fallback_still_builds(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(catalogue, "remove_cycles", lambda g, root: [])
    monkeypatch.setattr(catalogue, "all_back_edges", lambda g, root: [])   # fallback finds nothing
    with caplog.at_level(logging.WARNING, logger="app"):
        cat = build(make_data(tmp_path, CYCLIC), "R")
    assert "CRITICAL" in [r.levelname for r in caplog.records]
    assert set(cat.part_info) == {"R", "A", "B", "C", "D", "E"}
    assert cat.part_info["R"]["total_quantity"] == 1
    assert all(cat.part_info[x]["total_quantity"] == 0 for x in "ABCDE")    # unplaced parts
    assert cat.paths("A") == [["R", "A"]]
    assert cat.paths("B") == []                                            # no loop, no hang
    assert cat.counts["parts"] == 6
