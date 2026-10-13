"""PRODUCT.md 12.12: request and build times on real and synthetic shapes.

Each test prints nodes, edges, max depth, expected path count and measured times (see with -s).
The 1,048,576-path lattice is the documented limit: opt-in with RUN_SLOW=1 (decision 29)."""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import DATA_DIR
from app.main import app
from tests.conftest import build, make_data


def timed(fn, *args):
    t = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - t


def report(name, cat, depth, expected_paths, **times):
    edges = sum(len(info["children"]) for info in cat.part_info.values())
    shown = ", ".join(f"{k} {v:.3f}s" for k, v in times.items())
    print(f"\n[{name}] nodes={len(cat.part_info)} edges={edges} max_depth={depth} "
          f"paths_to_bottom={expected_paths} | {shown}")


def lattice(layers: int) -> list[tuple]:
    """R -> 2 nodes per layer, each linked to both nodes of the next layer -> BOTTOM: 2**layers paths."""
    rows = [("R", "L01A", 1), ("R", "L01B", 1)]
    for i in range(1, layers):
        for a in "AB":
            for b in "AB":
                rows.append((f"L{i:02d}{a}", f"L{i + 1:02d}{b}", 1))
    rows += [(f"L{layers:02d}A", "BOTTOM", 1), (f"L{layers:02d}B", "BOTTOM", 1)]
    return rows


def api_client(monkeypatch, data_dir, root):
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "ROOT_PN", root)
    return TestClient(app)


def slowest(client, urls):
    worst = 0.0
    for url in urls:
        r, t = timed(client.get, url)
        assert r.status_code == 200, url
        worst = max(worst, t)
    return worst


def test_real_data_every_request_fast(monkeypatch):
    cat, build_t = timed(build, DATA_DIR, "AS-40000")
    pns = sorted(cat.part_info)
    urls = ["/health", "/api/validation"] + [f"/api/parts/{pn}" for pn in pns] \
        + [f"/api/parts/{pn}/paths" for pn in pns] + [f"/api/serial/{s}" for s in (0, 1000, 2500, 5000)]
    with api_client(monkeypatch, DATA_DIR, "AS-40000") as c:
        worst = slowest(c, urls)
    depth = max(len(p) for pn in pns for p in cat.paths(pn)) - 1
    report(f"real data, {len(urls)} requests", cat, depth, "-", build=build_t, slowest_request=worst)
    assert worst < 0.5


def test_deep_chain(tmp_path, monkeypatch):
    n = 2000
    d = make_data(tmp_path, [(f"C{i:04d}", f"C{i + 1:04d}", 1) for i in range(n)])
    cat, build_t = timed(build, d, "C0000")
    with api_client(monkeypatch, d, "C0000") as c:
        worst = slowest(c, [f"/api/parts/C{n:04d}", f"/api/parts/C{n:04d}/paths", "/api/parts/C1000/paths"])
    report("deep chain", cat, n, 1, build=build_t, slowest_request=worst)
    assert build_t < 5
    assert worst < 0.5


def test_diamond_lattice_65536_paths(tmp_path, monkeypatch):
    layers = 16
    d = make_data(tmp_path, lattice(layers))
    cat, build_t = timed(build, d, "R")
    assert cat.precomputed_paths is not None                       # 196,607 paths in total: under the limit
    with api_client(monkeypatch, d, "R") as c:
        r, paths_t = timed(c.get, "/api/parts/BOTTOM/paths")
    assert r.status_code == 200
    assert len(r.json()["paths"]) == 2 ** layers
    report("diamond lattice", cat, layers + 1, 2 ** layers, build=build_t, paths_request=paths_t)
    assert build_t < 10
    assert paths_t < 1


@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="opt-in: set RUN_SLOW=1 (decision 29)")
@pytest.mark.xfail(strict=False, reason="documented limit: 1,048,576 paths are computed on request")
def test_large_lattice_documented_limit(tmp_path):
    layers = 20
    d = make_data(tmp_path, lattice(layers))
    cat, build_t = timed(build, d, "R")
    assert cat.precomputed_paths is None                           # lazy mode: too many paths to precompute
    paths, paths_t = timed(cat.paths, "BOTTOM")
    assert len(paths) == 2 ** layers
    report("large lattice", cat, layers + 1, 2 ** layers, build=build_t, paths_computation=paths_t)
    assert paths_t < 1                                             # expected to fail: recorded, not required
