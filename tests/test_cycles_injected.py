"""PRODUCT.md 12.7: inject bad "points back up" edges into the clean visible BOM and check
that cycle removal takes out exactly the injected edges."""
from __future__ import annotations

import logging
import random
from collections import defaultdict

import pytest

from app.catalogue import find_first_back_edge, reachable, remove_cycles
from app.config import DATA_DIR
from app.loader import load_all

ROOT = "AS-40000"
TRIALS = 1000


@pytest.fixture(scope="module")
def clean():
    """(graph, parts, ancestors) of the visible BOM with its own cycle removed."""
    edges, _, _ = load_all(DATA_DIR)
    reach = reachable(edges, ROOT)
    g = {p: dict(cs) for p, cs in edges.items() if p in reach}
    logging.getLogger("app").disabled = True
    try:
        remove_cycles(g, ROOT)
    finally:
        logging.getLogger("app").disabled = False

    up = defaultdict(set)
    for p, cs in g.items():
        for c in cs:
            up[c].add(p)
    parts = sorted(reachable(g, ROOT) - {ROOT})
    ancestors = {}
    for u in parts:
        seen, stack = set(), [u]
        while stack:
            for p in up[stack.pop()]:
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        ancestors[u] = sorted(seen - {ROOT})
    return g, parts, ancestors


def inject(rng, parts, ancestors, k):
    """k distinct u -> v edges, v an ancestor of u in the clean BOM (never the root)."""
    chosen = []
    while len(chosen) < k:
        u = rng.choice(parts)
        if not ancestors[u]:
            continue
        edge = (u, rng.choice(ancestors[u]))
        if edge not in chosen:
            chosen.append(edge)
    return chosen


def plain_dfs_removal(g, root):
    removed = set()
    while (found := find_first_back_edge(g, root)) is not None:
        u, c, _ = found
        removed.add((u, c))
        del g[u][c]
    return removed


@pytest.mark.parametrize("seed", [11, 12, 13])
@pytest.mark.parametrize("k, required", [(1, 1000), (3, 1000), (5, 995)])
def test_injected_cycles(clean, seed, k, required, caplog):
    caplog.set_level(logging.CRITICAL, logger="app")       # silence 1 WARNING per removed edge
    g, parts, ancestors = clean
    rng = random.Random(seed)
    score = plain = 0
    for _ in range(TRIALS):
        injected = set(inject(rng, parts, ancestors, k))
        trial = {p: dict(cs) for p, cs in g.items()}
        for u, v in injected:
            trial.setdefault(u, {})[v] = 1
        plain_graph = {p: dict(cs) for p, cs in trial.items()}
        removed = {(p, c) for p, c, _ in remove_cycles(trial, ROOT)}
        score += removed == injected
        plain += plain_dfs_removal(plain_graph, ROOT) == injected
    print(f"seed={seed} edges={k}: rule {score}/{TRIALS}, plain DFS {plain}/{TRIALS}")
    assert score >= required
