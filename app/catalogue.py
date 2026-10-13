"""Stages 4-6: graph, cycles, totals, paths, statuses, serials (PRODUCT.md section 8).

No recursion anywhere: BOMs can be thousands of levels deep."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.loader import load_all, loose_key, norm_pn
from models import ServiceDecision

log = logging.getLogger("app")

Graph = dict[str, dict[str, int]]          # parent -> child -> quantity


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def reachable(g: Graph, root: str) -> set[str]:
    """(8.2) Every part reachable from root, by iterative stack search."""
    seen = {root}
    stack = [root]
    while stack:
        for c in g.get(stack.pop(), {}):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def without_edge(g: Graph, p: str, c: str) -> Graph:
    g2 = dict(g)
    g2[p] = {k: v for k, v in g[p].items() if k != c}
    return g2


def find_first_back_edge(g: Graph, root: str):
    """Iterative colour DFS, children in sorted order.
    Returns (u, c, cycle) for the first back edge u->c found, where `cycle` is the
    DFS stack slice [c, ..., u] (so the cycle is c -> ... -> u -> c). Returns None if acyclic."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {root: GRAY}
    stack = [(root, iter(sorted(g.get(root, {}))))]
    path = [root]
    while stack:
        node, it = stack[-1]
        advanced = False
        for child in it:
            c = color.get(child, WHITE)
            if c == GRAY:
                i = path.index(child)
                return node, child, path[i:]
            if c == WHITE:
                color[child] = GRAY
                stack.append((child, iter(sorted(g.get(child, {})))))
                path.append(child)
                advanced = True
                break
        if not advanced:
            color[node] = BLACK
            stack.pop()
            path.pop()
    return None


def all_back_edges(g: Graph, root: str) -> list[tuple[str, str, int]]:
    """Every DFS back edge in one pass (children sorted). Removing them all leaves a DAG."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {root: GRAY}
    stack = [(root, iter(sorted(g.get(root, {}))))]
    out = []
    while stack:
        node, it = stack[-1]
        advanced = False
        for child in it:
            c = color.get(child, WHITE)
            if c == GRAY:
                out.append((node, child, g[node][child]))
            elif c == WHITE:
                color[child] = GRAY
                stack.append((child, iter(sorted(g.get(child, {})))))
                advanced = True
                break
        if not advanced:
            color[node] = BLACK
            stack.pop()
    return out


# ---------------------------------------------------------------------------
# Cycle removal (8.3)
# ---------------------------------------------------------------------------


def choose_cut(g: Graph, root: str, u: str, c: str, cycle: list[str], reach_before: set[str]):
    """Prefer cutting the cycle edge out of a 'fake container': a part x on the cycle that
    contains nothing outside the cycle, while the cycle part that contains x (its
    predecessor on the cycle) is a real assembly that contains something outside the cycle.
    Accept such a cut only if no part drops out of the machine.
    Otherwise use the plain DFS back edge (u, c)."""
    on_cycle = set(cycle)
    n = len(cycle)
    for i, x in enumerate(cycle):                 # cycle = [c, ..., u]; edges x -> cycle[i+1]
        prev = cycle[i - 1]                       # i == 0 wraps to u, which contains c
        nxt = cycle[(i + 1) % n]
        x_fake = all(k in on_cycle for k in g.get(x, {}))
        prev_real = any(k not in on_cycle for k in g.get(prev, {}))
        if x_fake and prev_real:
            if reachable(without_edge(g, x, nxt), root) == reach_before:
                return (x, nxt), "fake_container"
    return (u, c), "back_edge"


def cycle_pass_cap(g: Graph) -> int:
    return sum(len(v) for v in g.values()) + 1            # each pass removes one edge


def remove_cycles(g: Graph, root: str) -> list[tuple[str, str, int]]:
    """Remove cycle edges from g in place; return them as (parent, child, quantity)."""
    removed = []
    reach_before = reachable(g, root)
    for _ in range(cycle_pass_cap(g)):
        found = find_first_back_edge(g, root)
        if found is None:
            return removed
        u, c, cycle = found
        try:
            (p, ch), why = choose_cut(g, root, u, c, cycle, reach_before)
        except Exception as e:                            # safety net
            log.error("choose_cut failed (%r); using plain back edge", e)
            (p, ch), why = (u, c), f"back_edge_after_error:{e!r}"
        removed.append((p, ch, g[p][ch]))
        log.warning("cycle edge removed: %s -> %s x%s (%s)", p, ch, g[p][ch], why)
        del g[p][ch]
    log.error("cycle removal hit its iteration cap; using fallback")
    # Fallback: strip every remaining DFS back edge in one pass (provably leaves a DAG)
    for (p, ch, q) in all_back_edges(g, root):
        removed.append((p, ch, q))
        del g[p][ch]
        log.warning("cycle edge removed: %s -> %s x%s (fallback)", p, ch, q)
    return removed


# ---------------------------------------------------------------------------
# Topological order (8.4)
# ---------------------------------------------------------------------------


def topo_order(g: Graph, root: str) -> tuple[list[str], set[str]]:
    nodes = reachable(g, root)
    indeg = {n: 0 for n in nodes}
    for p in nodes:
        for c in g.get(p, {}):
            indeg[c] += 1                      # only edges between reachable parts
    queue = deque(sorted(n for n in nodes if indeg[n] == 0))   # just [root]
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for c in sorted(g.get(n, {})):
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    return order, nodes


def checked_topo_order(g: Graph, root: str, removed: list[tuple[str, str, int]]) -> tuple[list[str], set[str]]:
    """topo_order with the 8.4 self-check: never crash if a cycle survived."""
    order, nodes = topo_order(g, root)
    if len(order) < len(nodes):
        log.error("topological sort placed %d of %d parts; a cycle survived, stripping back edges",
                  len(order), len(nodes))
        for (p, ch, q) in all_back_edges(g, root):
            removed.append((p, ch, q))
            del g[p][ch]
            log.warning("cycle edge removed: %s -> %s x%s (fallback)", p, ch, q)
        order, nodes = topo_order(g, root)
        if len(order) < len(nodes):
            log.critical("topological sort still incomplete (%d of %d); unplaced parts get total 0",
                         len(order), len(nodes))
    return order, nodes


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Catalogue:
    root: str
    part_info: dict[str, dict]
    removed_edges: list[tuple[str, str, int]]
    counts: dict[str, int]
    parents: dict[str, list[str]]
    precomputed_paths: dict[str, list[list[str]]] | None
    serial_index: list[tuple[bool, tuple[tuple[int | None, int | None], ...]]]
    machine_loose: dict[str, list[str]]       # loose_key -> machine part numbers (9.4)

    def paths(self, x: str) -> list[list[str]]:
        """(8.7) Every root-to-x path, sorted. Precomputed, or computed now (no cache)."""
        if self.precomputed_paths is not None:
            return self.precomputed_paths[x]
        return paths_to(x, self.root, self.parents)

    def applicable(self, s: int) -> int:
        """(8.9) Number of ready parts that fit serial s; each part counts at most once."""
        n = 0
        for unrestricted, ranges in self.serial_index:
            if unrestricted or any((lo is None or lo <= s) and (hi is None or s <= hi) for lo, hi in ranges):
                n += 1
        return n


def paths_to(x: str, root: str, parents: dict[str, list[str]]) -> list[list[str]]:
    out, stack = [], [(x, (x,))]
    while stack:
        node, suffix = stack.pop()
        if node == root:
            out.append(list(reversed(suffix)))
            continue
        for p in parents.get(node, []):
            stack.append((p, suffix + (p,)))
    out.sort()                    # list-of-str comparison = "part number by part number from the top"
    return out


def _status(x: str, master: dict, service: dict[str, ServiceDecision]) -> str:
    if x not in master:
        return "missing"
    decision = service.get(x)
    return "ready" if decision is not None and decision.replaceable else "not_replaceable"


def assemble(edges: Graph, master: dict[str, dict[str, str]], service: dict[str, ServiceDecision],
             root: str) -> Catalogue:
    """Stages 4-6 on already-loaded data."""
    # 8.1-8.2: root and reachability; orphan edges never enter g
    reach = reachable(edges, root)
    g: Graph = {p: dict(children) for p, children in edges.items() if p in reach}

    # 8.3-8.4: cycles and topological order
    removed = remove_cycles(g, root)
    order, nodes = checked_topo_order(g, root, removed)

    # 8.5: totals and path counts along the topological order
    total = {n: 0 for n in nodes}
    count = {n: 0 for n in nodes}
    total[root] = 1
    count[root] = 1
    placed = set(order)
    for n in order:
        for c, q in g.get(n, {}).items():
            if c in placed:
                total[c] += total[n] * q
                count[c] += count[n]

    # 8.6: parents (via a reverse index) and children. Only placed parents count: if the
    # CRITICAL branch of 8.4 left a cycle among unplaced parts, paths_to must not loop on it.
    # In every normal build all parts are placed, so nothing is dropped.
    parent_sets: dict[str, set[str]] = {n: set() for n in nodes}
    for p in placed:
        for c in g.get(p, {}):
            parent_sets[c].add(p)
    parents = {n: sorted(ps) for n, ps in parent_sets.items()}
    children = {n: [{"part_number": c, "quantity": q} for c, q in sorted(g.get(n, {}).items())]
                for n in nodes}

    # 8.7: paths, precomputed when the total is small enough
    for n in sorted(nodes):
        if count[n] > config.MAX_PATHS_WARN:
            log.warning("part %s has %d paths", n, count[n])
    precomputed = None
    if sum(count.values()) <= config.PATHS_PRECOMPUTE_LIMIT:
        precomputed = {n: paths_to(n, root, parents) for n in nodes}

    # 8.8 + 8.10: part info, with safe defaults if anything fails
    part_info: dict[str, dict] = {}
    for x in sorted(nodes):
        try:
            in_master = x in master
            part_info[x] = {
                "part_number": x,
                "description": master[x]["description"] if in_master else None,
                "revision": master[x]["revision"] if in_master else None,
                "status": _status(x, master, service),
                "total_quantity": total[x],
                "parents": parents[x],
                "children": children[x],
            }
        except Exception as e:
            log.critical("part_info for %s failed (%r); using safe defaults", x, e)
            part_info[x] = {
                "part_number": x, "description": None, "revision": None,
                "status": "missing", "total_quantity": 0,
                "parents": parents.get(x, []), "children": children.get(x, []),
            }

    # 8.9: serial index over ready parts, in part-number order
    serial_index = [(service[x].unrestricted, tuple(service[x].ranges))
                    for x in sorted(part_info) if part_info[x]["status"] == "ready"]

    # 8.11: validation counts
    statuses = [info["status"] for info in part_info.values()]
    counts = {
        "parts": len(part_info),
        "ready": statuses.count("ready"),
        "missing": statuses.count("missing"),
        "not_replaceable": statuses.count("not_replaceable"),
    }
    log.info("catalogue built: %s; %d cycle edge(s) removed", counts, len(removed))

    machine_loose: dict[str, list[str]] = {}
    for x in sorted(part_info):
        machine_loose.setdefault(loose_key(x), []).append(x)

    return Catalogue(
        root=root,
        part_info=part_info,
        removed_edges=removed,
        counts=counts,
        parents=parents,
        precomputed_paths=precomputed,
        serial_index=serial_index,
        machine_loose=machine_loose,
    )


def build_catalogue(data_dir: Path, root: str) -> Catalogue:
    """(8.12) Stages 1-6. Raises only StartupError."""
    edges, master, service = load_all(data_dir)
    return assemble(edges, master, service, norm_pn(root))
