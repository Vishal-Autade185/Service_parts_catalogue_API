"""PRODUCT.md 12.10: random small BOMs (duplicates, cycles, orphans, invalid rows) checked
against an independently written brute-force reference.

The reference enumerates paths recursively over the same cleaned, cycle-removed edges and
derives totals, paths, parents and children from them."""
from __future__ import annotations

import random

import pytest

from app.loader import load_all
from tests.conftest import build, make_data

ROOT = "P00"


def random_bom(rng: random.Random) -> list[tuple]:
    n = rng.randint(5, 30)
    parts = [f"P{i:02d}" for i in range(n)]
    rows: list[tuple] = []
    for i in range(1, n):
        if rng.random() < 0.85:                                   # else: orphan (no parent in the machine)
            rows.append((parts[rng.randrange(i)], parts[i], rng.randint(1, 5)))
    for _ in range(rng.randint(0, n)):                            # extra edges: shared parts and cycles
        p, c = rng.sample(parts, 2)
        rows.append((p, c, rng.randint(1, 5)))
    for _ in range(rng.randint(0, 3)):                            # orphan assembly pointing into the machine
        rows.append((f"O{rng.randint(0, 9)}", rng.choice(parts), rng.randint(1, 3)))
    for r in rng.sample(rows, min(len(rows), rng.randint(0, 4))):  # duplicates, same or different quantity
        rows.append((r[0], r[1], rng.choice([r[2], r[2], rng.randint(1, 5)])))
    for _ in range(rng.randint(0, 4)):                            # invalid rows
        p = rng.choice(parts)
        rows.append(rng.choice([
            (p, rng.choice(parts), rng.choice(["abc", "0", "-1", "2.5", ""])),
            (p, p, 1),
            ("", rng.choice(parts), 1),
        ]))
    rng.shuffle(rows)
    return rows


def reference(edges: dict[str, dict[str, int]], root: str):
    """Recursive brute force: every root-to-part path, then totals, parents and children."""
    paths: dict[str, list[list[str]]] = {}

    def walk(node, path, seen):
        assert node not in seen, f"cycle survived: {path + [node]}"
        path = path + [node]
        paths.setdefault(node, []).append(path)
        for child in edges.get(node, {}):
            walk(child, path, seen | {node})

    walk(root, [], frozenset())
    totals, parents = {}, {}
    for x, ps in paths.items():
        total = 0
        for p in ps:
            prod = 1
            for a, b in zip(p, p[1:]):
                prod *= edges[a][b]
            total += prod
        totals[x] = total
        parents[x] = sorted({p[-2] for p in ps if len(p) > 1})
    children = {x: [{"part_number": c, "quantity": q} for c, q in sorted(edges.get(x, {}).items())] for x in paths}
    return {x: sorted(ps) for x, ps in paths.items()}, totals, parents, children


@pytest.mark.parametrize("seed", range(200))
def test_random_graph_matches_reference(tmp_path, seed):
    rng = random.Random(seed)
    d = make_data(tmp_path, random_bom(rng))
    cat = build(d, ROOT)

    edges, _, _ = load_all(d)                                     # the same cleaned edges ...
    for p, c, _ in cat.removed_edges:                             # ... with the same cycle edges removed
        del edges[p][c]
    paths, totals, parents, children = reference(edges, ROOT)

    assert set(cat.part_info) == set(paths)
    for x in paths:
        info = cat.part_info[x]
        assert info["total_quantity"] == totals[x], x
        assert info["parents"] == parents[x], x
        assert info["children"] == children[x], x
        assert cat.paths(x) == paths[x], x
