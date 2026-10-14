# Product Specification: Service Parts Catalogue API

**Version 5.0.** This replaces v4.1. It is written so that a developer or an AI coding agent can implement it end to end without making design decisions of their own. Every decision below is final; if implementation reveals a reason to change one, change it here **and** in DATA.md in the same commit.

---

## 0. Instructions for the implementer

1. Implement the phases in section 13 **in order**. Each phase ends with a commit. Do not start a phase until the previous phase's tests pass.
2. **Never special-case a row, a part number or a value seen in the visible data.** The grader replaces `data/` with a different export containing new problems. Every rule must be general.
3. **Never crash on bad data.** The only fatal startup errors are a missing file and a missing required column (section 3.1). Everything else is skipped and the service keeps going.
4. **No recursion anywhere** in graph code. BOMs can be thousands of levels deep.
5. **Determinism.** Wherever order matters, sort by part number. Two runs on the same data must give byte-identical responses.
6. Use only the Python standard library plus the packages in `requirements.txt` (section 11.1). No network calls at runtime.
7. There is **no audit report**. Bad rows are simply skipped. Use Python's standard `logging` (logger name `app`) only for the few warnings listed in section 7.

---

## 1. Overview

Build a REST API for a fictional bottling machine, the AM-700 by Arcadia Machines. The service reads three CSV files from three systems that disagree with each other, reconciles them into one parts catalogue, and answers four questions for a field service engineer:

- What is this part?
- Where does it sit in the machine?
- Can it be replaced on site?
- Does it fit this machine's serial number?

**Root part:** `AS-40000`. The root is configurable (`ROOT_PN`, default `AS-40000`) so tests can use `AS-1` for the worked example in Appendix Q of the brief.

### 1.1 Core requirements (from the brief)

| Requirement | Consequence |
|---|---|
| Works offline | No network at request time |
| Starts from a fresh clone with one documented command | `docker compose up --build`, with `bash run.sh` as the no-Docker alternative |
| Every request answers in under 1 second | All answers precomputed at startup; requests are dictionary lookups |
| Graded by exact field-by-field match on hidden data | Every ambiguity is a written decision (this file and DATA.md) |
| `GET /health` returns `{"status": "ok"}` once ready | Catalogue built in FastAPI `lifespan` before the server accepts requests |
| API and page served by one process on port 8000, page at `/` | Single FastAPI app |

### 1.2 Guiding principle: which mistake is worse

The brief states that a wrong part shipped costs the customer a day of downtime.

- **Dangerous mistake:** a part shown as `ready`, or as fitting a serial, when it does not. A wrong part ships.
- **Safe mistake:** a part shown as `not_replaceable`, `missing`, or "does not fit". The engineer double-checks or escalates.

Rules:
1. Where Appendix Q of the brief states a rule, follow it exactly.
2. Where the brief is silent or the data contradicts itself, choose the reading that produces the safe mistake.
3. **Exception — BOM structure.** Dropping a BOM edge removes the whole subtree below it (404s instead of answers). For structure, keep every edge whose values can be read with confidence. Apply caution only to outputs that mean "ship this part": status, serial applicability, revision.

---

## 2. Input data

Files live in `data/` at the repository root. The data directory is resolved as:

```python
DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
```

It is **never** resolved from the current working directory.

| File | Required columns | Optional (ignored) columns |
|---|---|---|
| `bom.csv` | `parent_pn`, `child_pn`, `quantity` | anything else |
| `parts_master.csv` | `part_number`, `revision`, `description` | `category`, `unit_cost`, anything else |
| `service_parts.csv` | `part_number`, `field_replaceable`, `serial_from`, `serial_to` | anything else |

`category` and `unit_cost` are **not** required and **never** validated. A bad value in them must never cause a row to be rejected.

---

## 3. Stage 1 — reading files safely (`app/loader.py`)

### 3.1 `read_csv(path, required_columns) -> list[Row]`

1. If the file does not exist → raise `StartupError(f"{name}: file not found at {path}")`.
2. Read bytes. Remove every NUL byte (`b"\x00"`).
3. Decode with `utf-8-sig`. On `UnicodeDecodeError`, decode with `cp1252` using `errors="replace"`.
4. Parse with `csv.reader` over `io.StringIO(text)` (handles quoted fields and CRLF).
5. The first non-blank line is the header. Canonicalise each header cell:
   ```python
   def canon_header(h: str) -> str:
       h = h.replace("﻿", "").strip().strip('"').strip().lower()
       return re.sub(r"[\s\-]+", "_", h)
   ```
6. If any required column is missing → raise `StartupError(f"{name}: missing required column(s) {sorted(missing)}; found {header}")`.
7. For each following line (keep a 1-based line number matching the file):
   - Skip if every cell is blank after `strip()`.
   - Pad with `""` or trim so the row has exactly as many cells as the header.
   - Yield `Row(line=lineno, values=dict(zip(header, cells)))`.
8. If the header appears again as a data row, do nothing special; it fails validation later and is skipped.

### 3.2 Per-row safety

Every per-row operation in stages 2 and 3 runs inside `try/except Exception`. On an unexpected exception, skip that row and continue with the next one.

### 3.3 Fatal errors

`StartupError` is the **only** exception allowed to stop startup. Its message must name the file and the problem. Missing data cannot be worked around, so failing loudly is correct.

---

## 4. Stage 2 — cleaning cell values (`app/loader.py`)

### 4.1 Part numbers — `norm_pn(value: str) -> str`

```python
import re, unicodedata

DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")

def norm_pn(v: str | None) -> str:
    v = unicodedata.normalize("NFKC", v or "")                       # full-width -> ASCII, NBSP -> space
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Cf")  # zero-width, joiners, BOM, soft hyphen
    v = v.translate(DASHES)                                          # dash look-alikes -> "-"
    v = "".join(v.split())                                           # remove ALL whitespace, incl. internal
    return v.upper()
```

- Applied to every part-number cell in all three files **and** to the part number in every request URL.
- Separators (`-`, `_`, `#`, `/`) are **kept** by `norm_pn`. `GF#48488` and `GF-48488` are different strings after `norm_pn`; section 6.4 handles cross-file variants.

Required tests (exact):
```python
assert norm_pn("GF​48488") == "GF48488"
assert norm_pn("GF 48488") == "GF48488"
assert norm_pn(" fa-30013 ") == "FA-30013"
assert norm_pn("ＡＳ-40000") == "AS-40000"
assert norm_pn("AS–40000") == "AS-40000"
assert norm_pn("AS 40000") == "AS40000"
assert norm_pn("GF#48488") != norm_pn("GF-48488")
assert norm_pn(None) == ""
```

### 4.2 Loose key — `loose_key(pn: str) -> str`

```python
def loose_key(pn: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", pn)   # pn is already norm_pn'd
```

Used only for cross-file alias resolution (section 6.4) and as a fallback in URL lookup (section 9.4). Never used as an output value.

### 4.3 Whole numbers — `parse_int(value) -> int | BLANK | INVALID`

`BLANK` and `INVALID` are module-level sentinel objects.

```python
NULL_TOKENS = {"", "NAN", "NULL", "NONE", "N/A", "NA", "-"}
_INT = re.compile(r"[+-]?[0-9]+")
_INT_DEC = re.compile(r"([+-]?[0-9]+)\.0+")

def parse_int(v):
    s = (v or "").strip().replace(",", "")
    if s.upper() in NULL_TOKENS:
        return BLANK
    if _INT.fullmatch(s):
        return int(s)
    m = _INT_DEC.fullmatch(s)
    if m:
        return int(m.group(1))
    return INVALID
```

Use `[0-9]`, never `\d` (which matches non-ASCII digits). The regex check runs **before** `int()`, so `1_0` (which Python's `int()` would accept) is `INVALID`.

| Input | Result |
|---|---|
| `"3"`, `" 3 "`, `"+3"`, `"-5"` | the integer |
| `"3.0"`, `"1000.00"` | the integer |
| `"1,000"` | `1000` |
| `""`, `"NULL"`, `"N/A"`, `"na"`, `"NaN"`, `"None"`, `"-"` | `BLANK` |
| `"2.5"`, `"abc"`, `"1e3"`, `"1_0"`, `"3.0.0"` | `INVALID` |

### 4.4 Replaceable flag — `parse_flag(value) -> ("Y" | "N", known: bool)`

```python
YES = {"Y", "YES", "TRUE", "T", "1"}
NO = {"N", "NO", "FALSE", "F", "0", ""}

def parse_flag(v):
    s = (v or "").strip().upper()
    if s in YES: return "Y", True
    if s in NO:  return "N", True
    return "N", False          # unknown value: treated as N
```

### 4.5 Revision — `norm_rev(value) -> str` and `rev_key(rev) -> tuple`

```python
def norm_rev(v):  return (v or "").strip().upper()
def rev_key(r):   return (len(r), r)      # "" < "A" < "B" < "Z" < "AA"
```

### 4.6 Description

`(v or "").strip()`. A blank description stays `""`.

---

## 5. Stage 2 (continued) — row validation per file (`app/loader.py`)

Each loader returns typed rows. Validation of **all** rows happens before any grouping or deduplication.

### 5.0 Internal record types (`models/records.py`)

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Row:                     # one raw CSV line from the reader (section 3.1)
    line: int
    values: dict[str, str]

@dataclass(frozen=True)
class BomEdge:                 # one validated bom.csv row (5.1)
    parent: str
    child: str
    qty: int
    line: int

@dataclass(frozen=True)
class MasterRow:               # one validated parts_master.csv row (5.2)
    pn: str
    rev: str
    description: str
    line: int

@dataclass(frozen=True)
class ServiceRow:              # one validated service_parts.csv row (5.3)
    pn: str
    flag: str                  # "Y" or "N"
    lo: int | None
    hi: int | None
    range_valid: bool
    line: int

@dataclass
class ServiceDecision:         # one part's resolved service status (6.3)
    replaceable: bool = False
    unrestricted: bool = False
    ranges: list[tuple[int | None, int | None]] = field(default_factory=list)
```

Add `from __future__ import annotations` at the top of every module so `int | None` works on Python 3.9.

### 5.1 `bom.csv` → `BomEdge(parent, child, qty, line)`

| Check | Action if it fails |
|---|---|
| `parent = norm_pn(parent_pn)` is non-empty | skip |
| `child = norm_pn(child_pn)` is non-empty | skip |
| `parent != child` | skip |
| `q = parse_int(quantity)` is an `int` and `q > 0` | skip |

### 5.2 `parts_master.csv` → `MasterRow(pn, rev, description, line)`

| Check | Action if it fails |
|---|---|
| `pn = norm_pn(part_number)` is non-empty | skip |

`rev = norm_rev(revision)`; a blank revision is valid. `description` per 4.6.

### 5.3 `service_parts.csv` → `ServiceRow(pn, flag, lo, hi, range_valid, line)`

| Step | Rule |
|---|---|
| Part number | `pn = norm_pn(part_number)`; blank → skip |
| Flag | `flag, _ = parse_flag(field_replaceable)` |
| Bounds | `a = parse_int(serial_from)`, `b = parse_int(serial_to)` |
| Range validity (computed for every row; only used for Y rows) | see table below |

| `a` | `b` | Result |
|---|---|---|
| BLANK | BLANK | `lo=None, hi=None, range_valid=True` (unrestricted) |
| int | BLANK | `lo=a, hi=None, range_valid=True` (open upper bound) |
| BLANK | int | `lo=None, hi=b, range_valid=True` (open lower bound) |
| int | int, `a <= b` | `lo=a, hi=b, range_valid=True` |
| int | int, `a > b` | `range_valid=False` |
| INVALID on either side | — | `range_valid=False` |

---

## 6. Stage 3 — resolving conflicts (`app/loader.py`)

### 6.1 BOM deduplication

Group valid `BomEdge`s by `(parent, child)`.

- One row → keep it.
- Several rows, all the same quantity → keep one.
- Several rows, different quantities → keep the **most common** quantity; on a tie, the quantity of the **first** valid row (lowest line number).

Output: `edges: dict[str, dict[str, int]]` (parent → child → qty).

### 6.2 Revision selection

Group valid `MasterRow`s by `pn`.

- Keep the row with the highest `rev_key(rev)`.
- If two or more rows share that highest revision → keep the first (lowest line number).

Output: `master: dict[str, {"revision": str, "description": str}]`.

### 6.3 Service decision per part

Group `ServiceRow`s by `pn`.

| Situation | `replaceable` | `unrestricted` | `ranges` |
|---|---|---|---|
| No rows | False | — | — |
| Only N rows (including unknown flags) | False | — | — |
| At least one Y row **and** at least one N row | **False** (N wins) | — | — |
| Only Y rows | True | True if any Y row has `lo is None and hi is None and range_valid` | list of `(lo, hi)` from Y rows with `range_valid` and at least one bound set |

- Rows for parts not in the machine are ignored.
- A replaceable part with `unrestricted=False` and `ranges=[]` (every Y row had an invalid range) is still `ready`, but fits **no** serial.

Output: `service: dict[str, ServiceDecision]`.

### 6.4 Cross-file part-number aliases

Run after 6.1–6.3, before stage 4.

1. `bom_keys` = every parent and child in `edges`.
2. Build `bom_loose: dict[loose_key, set[pn]]` over `bom_keys`.
3. For every key in `master` and `service` that is **not** in `bom_keys`:
   - If `bom_loose[loose_key(pn)]` has **exactly one** spelling → re-key the entry to that spelling.
   - Otherwise leave it alone.
4. If re-keying makes two entries collide in `master` (both an alias and an exact key), keep the exact key's entry. For `service`, merge the rows and recompute 6.3.
5. Output always uses the BOM spelling.

---

## 7. Logging (no audit report)

There is no audit report and no audit script. The only diagnostics are a few standard-library log lines, written with `log = logging.getLogger("app")`:

| When | Level | Message contains |
|---|---|---|
| Startup finished | INFO | validation counts and number of cycle edges removed |
| A cycle edge is removed | WARNING | parent, child, quantity, rule (`back_edge`, `fake_container`, `fallback`) |
| A safety net fires (sections 8.3, 8.4, 8.10) | ERROR / CRITICAL | what failed and which fallback was used |
| A part has more than `MAX_PATHS_WARN` paths | WARNING | part number and path count |

The removed cycle edges are also kept on the catalogue as `catalogue.removed_edges: list[tuple[str, str, int]]`, because DATA.md and the tests need them.

---

## 8. Stage 4–6 — the catalogue (`app/catalogue.py`)

Input: `edges`, `master`, `service` from stage 3, plus `root`. Output: an immutable `Catalogue` object.

### 8.1 Root handling

`root = norm_pn(ROOT_PN)`. The root is always in the catalogue with `total_quantity = 1`, even if it appears nowhere in the BOM. If it has no BOM rows, the catalogue contains only the root.

### 8.2 Reachability

`reachable(graph, root)`: iterative stack-based search from `root` following edges. Edges whose parent is not reachable are **orphan edges**: exclude them from everything (they never contribute to `parents`, totals or paths).

### 8.3 Cycle removal

**Definition (Appendix Q):** the wrong relationship is the one that points back up from inside the machine — an assembly listed as containing a part that, coming down from the root, it already sits inside.

**Algorithm.** Work on a mutable copy `g` of the reachable graph.

```python
def find_first_back_edge(g, root):
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


def choose_cut(g, root, u, c, cycle, reach_before):
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


def remove_cycles(g, root):
    removed = []
    reach_before = reachable(g, root)
    max_iter = sum(len(v) for v in g.values()) + 1        # each pass removes one edge
    for _ in range(max_iter):
        found = find_first_back_edge(g, root)
        if found is None:
            return removed
        u, c, cycle = found
        try:
            (p, ch), why = choose_cut(g, root, u, c, cycle, reach_before)
        except Exception as e:                            # safety net
            (p, ch), why = (u, c), f"back_edge_after_error:{e!r}"
        removed.append((p, ch, g[p][ch]))
        log.warning("cycle edge removed: %s -> %s x%s (%s)", p, ch, g[p][ch], why)
        del g[p][ch]
    log.error("cycle removal hit its iteration cap; using fallback")
    # Fallback: strip every remaining DFS back edge in one pass (provably leaves a DAG)
    for (p, ch, q) in all_back_edges(g, root):
        removed.append((p, ch, q)); del g[p][ch]
        log.warning("cycle edge removed: %s -> %s x%s (fallback)", p, ch, q)
    return removed
```

**Why the fake-container check exists.** Plain DFS removes whichever edge closes the cycle in visiting order. When the bad edge starts at a heavily shared part (for example a fastener used in 19 assemblies that wrongly "contains" an assembly above it), DFS often reaches the fastener through another assembly first and then removes a **legitimate** edge into it. On the visible BOM with injected bad edges, plain DFS was right in 97.6% of single-edge trials and 91.1% of three-edge trials; with this check it is 1000/1000 for both. Requiring the predecessor to be a real assembly stops the check from firing on ordinary single-child assemblies.

**Known ambiguity.** When two real assemblies (each with other children) list each other, nothing in the data says which edge is wrong. The rule falls back to the plain DFS back edge. Document this in DATA.md and NOTES.md.

Properties the tests must check:
- Only edges that lie on a cycle are ever removed. Shared parts not in a cycle are never touched.
- The reachable set is identical before and after.
- Deterministic (children sorted).
- Each removed edge appears exactly once in `removed_edges`.

**Expected on the visible data:** exactly one edge removed, `AS-40209 → AS-40002` (quantity 1), rule `back_edge`.

### 8.4 Topological order (Kahn's algorithm) and self-check

```python
def topo_order(g, root):
    nodes = reachable(g, root)
    indeg = {n: 0 for n in nodes}
    for p in nodes:
        for c in g.get(p, {}):
            indeg[c] += 1                      # only edges between reachable parts
    queue = deque(sorted(n for n in nodes if indeg[n] == 0))   # just [root]
    order = []
    while queue:
        n = queue.popleft(); order.append(n)
        for c in sorted(g.get(n, {})):
            indeg[c] -= 1
            if indeg[c] == 0: queue.append(c)
    return order, nodes
```

- If `len(order) < len(nodes)`, a cycle survived (a bug). **Do not crash.** Log an ERROR, remove every DFS back edge from the remaining graph, and run `topo_order` again.
- If it still fails (should be impossible), log CRITICAL, compute totals for the parts that were placed, and give the rest `total_quantity = 0`. The service still starts.

### 8.5 Totals and path counts (dynamic programming)

```python
total = {n: 0 for n in order}; total[root] = 1
count = {n: 0 for n in order}; count[root] = 1
for n in order:
    for c, q in g.get(n, {}).items():
        total[c] += total[n] * q
        count[c] += count[n]
```

`total[x]` equals the sum, over every root-to-`x` path, of the product of edge quantities. Python integers do not overflow.

### 8.6 Parents and children

From the cleaned, reachable graph only:

```python
parents[x]  = sorted({p for p in nodes for c in g.get(p, {}) if c == x})   # build via a reverse index
children[x] = [{"part_number": c, "quantity": q} for c, q in sorted(g.get(x, {}).items())]
```

### 8.7 Paths

```python
def paths_to(x):
    out, stack = [], [(x, (x,))]
    while stack:
        node, suffix = stack.pop()
        if node == root:
            out.append(list(reversed(suffix))); continue
        for p in parents[node]:
            stack.append((p, suffix + (p,)))
    out.sort()                    # list-of-str comparison = "part number by part number from the top"
    return out
```

- Root → `[[root]]`.
- If `sum(count.values()) <= PATHS_PRECOMPUTE_LIMIT` (default 200,000): precompute `paths[x]` for every part at startup.
- Otherwise: compute `paths_to(x)` on each request, with **no cache**.
- If any single `count[x] > MAX_PATHS_WARN` (default 100,000): log a WARNING.
- Responses always contain the complete sorted list. Never truncate.

### 8.8 Status and part info

For every reachable part `x`:

| Situation | `status` | `description` | `revision` |
|---|---|---|---|
| `x` not in `master` | `missing` | `None` | `None` |
| in `master`, `service[x].replaceable` is True | `ready` | from master | from master |
| in `master`, otherwise | `not_replaceable` | from master | from master |

```python
part_info[x] = {
    "part_number": x, "description": ..., "revision": ..., "status": ...,
    "total_quantity": total[x], "parents": parents[x], "children": children[x],
}
```


### 8.9 Serial index

```python
serial_index = [(decision.unrestricted, tuple(decision.ranges))
                for x in sorted(part_info) if part_info[x]["status"] == "ready"
                for decision in [service[x]]]

def applicable(s: int) -> int:
    n = 0
    for unrestricted, ranges in serial_index:
        if unrestricted or any((lo is None or lo <= s) and (hi is None or s <= hi) for lo, hi in ranges):
            n += 1
    return n
```

Each part counts at most once.

### 8.10 Final consistency check

After building, assert for every reachable part: present in `part_info`, has a `total_quantity`, has a status. On any failure, log CRITICAL and fill safe defaults (`status` per 8.8, `total_quantity = 0`). Never raise.

### 8.11 Validation counts

```python
{"parts": len(part_info),
 "ready": #ready, "missing": #missing, "not_replaceable": #not_replaceable}
```

The three status counts always sum to `parts`.

### 8.12 Build entry point

```python
def build_catalogue(data_dir: Path, root: str) -> Catalogue
```

Runs stages 1–6 in order and returns the catalogue (including `removed_edges`). Raises only `StartupError`.

---

## 9. API (`app/main.py`)

All JSON, port 8000. The catalogue is built inside the FastAPI `lifespan` handler and stored on `app.state.catalogue`. Uvicorn does not accept connections until `lifespan` startup completes.

### 9.1 `GET /health`
`200 {"status": "ok"}`.

### 9.2 `GET /api/validation`
`200 {"parts": N, "ready": N, "missing": N, "not_replaceable": N}`.

### 9.3 Routes for parts — declaration order matters

Declare the paths route **first**, and use the `path` converter so part numbers containing `/` (sent as `%2F`) still reach the handler:

```python
@app.get("/api/parts/{part_number:path}/paths")
@app.get("/api/parts/{part_number:path}")
```

Keep `part_number` a plain `str`. Do the lookup in the handler so odd input gives 404, never 422.

### 9.4 Part lookup — `resolve_part(raw: str) -> str | None`

1. `pn = norm_pn(raw)` (FastAPI has already URL-decoded the path).
2. If `pn` is empty → `None`.
3. If `pn in part_info` → `pn`.
4. Else, if `loose_key(pn)` matches **exactly one** machine part (precomputed `machine_loose: dict[loose, set[pn]]`) → that part.
5. Else → `None`.

`GET /api/parts/{pn}`: `200` with `part_info[resolved]`, or `404 {"detail": "Part '<raw>' is not in the machine"}`.

`GET /api/parts/{pn}/paths`: `200 {"part_number": resolved, "paths": [...]}`, or the same 404.

The response's `part_number` is always the canonical (BOM) spelling, never the raw input.

### 9.5 `GET /api/serial/{serial}`

```python
s = serial.strip()
if not re.fullmatch(r"[+-]?[0-9]+", s):
    raise HTTPException(400, f"Serial '{serial}' is not a whole number")
try:
    n = int(s)
except ValueError:                       # Python's 4300-digit int() limit
    raise HTTPException(400, "Serial number is too long")
return {"serial": n, "applicable_parts": catalogue.applicable(n)}
```

- Accept negatives, zero, `+7`, leading zeros.
- Reject `abc`, `2500.5`, `2500.0`, `1e3`, empty → 400.
- No artificial length cap: any whole number Python can parse returns 200.

### 9.6 `GET /` — the page

`@app.get("/", include_in_schema=False)` returning `FileResponse(STATIC_DIR / "index.html")`. **Do not** mount `StaticFiles` at `/` (it can shadow API routes).

### 9.7 Global exception handler

Register a handler for `Exception` that logs the traceback and returns `500 {"detail": "Internal error"}`. It should never fire; it exists so a bug never returns an HTML traceback.

### 9.8 Page (`app/static/index.html`)

- Plain HTML + inline JS, no external resources.
- Four sections: validation (button only), part lookup (input + button), paths lookup (input + button), serial lookup (input + button).
- Each shows the HTTP status code and pretty-printed JSON response.
- Encode inputs with `encodeURIComponent`.
- Render responses with `textContent` only, never `innerHTML`.
- Show 4xx responses as readable errors (status + `detail`).

---

## 10. Response models (`models/responses.py`)

Response models declare **types only — no numeric constraints**. Constraints on outputs turn a data quirk into a 500.

```python
class PartChild(BaseModel):
    part_number: str
    quantity: int

class PartInfoResponse(BaseModel):
    part_number: str
    description: str | None
    revision: str | None
    status: Literal["ready", "missing", "not_replaceable"]
    total_quantity: int
    parents: list[str]
    children: list[PartChild]

class PathsResponse(BaseModel):
    part_number: str
    paths: list[list[str]]

class ValidationCounts(BaseModel):
    parts: int; ready: int; missing: int; not_replaceable: int

class SerialApplicableResponse(BaseModel):
    serial: int
    applicable_parts: int

class HealthResponse(BaseModel):
    status: Literal["ok"]

class ErrorResponse(BaseModel):
    detail: str
```

Field order in JSON must match the order above (it matches the brief).

---

## 11. Configuration, project structure and deployment

### 11.1 `requirements.txt`

Pin exact versions. Suggested baseline (verify they install on Python 3.9–3.12 before committing):

```text
fastapi==0.115.0
uvicorn==0.30.6
pydantic==2.9.2
httpx==0.27.2
pytest==8.3.3
```

`httpx` is required by FastAPI's `TestClient`; `pytest` runs the tests. Both are small, so one file keeps setup simple.

### 11.2 `app/config.py`

| Name | Env var | Default |
|---|---|---|
| `ROOT_PN` | `ROOT_PN` | `AS-40000` |
| `DATA_DIR` | `DATA_DIR` | `<repo root>/data` |
| `PATHS_PRECOMPUTE_LIMIT` | `PATHS_PRECOMPUTE_LIMIT` | `200000` |
| `MAX_PATHS_WARN` | `MAX_PATHS_WARN` | `100000` |
| `LOG_LEVEL` | `LOG_LEVEL` | `INFO` |

### 11.3 Project structure

```text
bruviti-use-case-5/
├── app/                        # application logic
│   ├── __init__.py
│   ├── config.py
│   ├── loader.py               # stages 1-3: read CSVs, clean values, validate rows, resolve conflicts
│   ├── catalogue.py            # stages 4-6: graph, cycles, totals, paths, statuses, serials
│   ├── main.py                 # FastAPI app, lifespan, routes
│   └── static/
│       └── index.html
├── models/                     # data shapes only, no logic
│   ├── __init__.py             # re-exports everything below
│   ├── records.py              # internal dataclasses (section 5.0)
│   └── responses.py            # Pydantic API response models (section 10)
├── data/                       # visible CSVs (also baked into the Docker image)
│   ├── bom.csv
│   ├── parts_master.csv
│   └── service_parts.csv
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # helpers: write CSVs to tmp_path, build catalogue
│   ├── test_loader.py
│   ├── test_catalogue.py
│   ├── test_worked_example.py
│   ├── test_real_data.py
│   ├── test_cycles_injected.py
│   ├── test_safety_nets.py
│   ├── test_invariance.py
│   ├── test_random_crosscheck.py
│   ├── test_api.py
│   └── test_performance.py
├── .gitignore
├── .gitattributes
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── run.sh
├── Makefile
├── requirements.txt
├── README.md
├── DATA.md
├── NOTES.md
├── AI.md
└── PRODUCT.md
```

Folder rules:

| Folder | Holds | May import from |
|---|---|---|
| `models/` | Data shapes only: dataclasses and Pydantic classes, no functions with logic | Standard library and `pydantic` only — **never** `app` (prevents circular imports) |
| `app/` | All logic: reading, cleaning, graph, API | `models` |
| `data/` | The three CSVs. The grader replaces this folder | — |
| `tests/` | All tests and fixtures | `app`, `models` |

- Every command runs from the repository root (`uvicorn app.main:app`, `pytest`). Uvicorn, `python -m` and pytest all put the root on the import path, so `import models` and `import app` both work without installing the project.
- `app/loader.py` is organised top to bottom in four labelled blocks: (1) value helpers — `norm_pn`, `loose_key`, `parse_int`, `parse_flag`, `norm_rev`, `rev_key`; (2) `read_csv`; (3) per-file validation; (4) conflict resolution and `load_all(data_dir) -> (edges, master, service)`. Only `load_all`, `StartupError` and the value helpers are used outside the file.
- `models/__init__.py` re-exports every class, so the rest of the code writes `from models import BomEdge, PartInfoResponse`.
- `DATA_DIR` still resolves from `app/config.py` as `Path(__file__).resolve().parent.parent / "data"` (the repository root's `data/`).

### 11.4 `.gitattributes`

```text
* text=auto
*.sh text eol=lf
Dockerfile text eol=lf
```

### 11.5 `.gitignore`

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

### 11.6 `.dockerignore` (must **not** exclude `data/`)

```text
.venv
.git
__pycache__
*.pyc
.pytest_cache
```

### 11.7 `Dockerfile`

Comments must be on their own lines. Docker does not support comments after an instruction; a trailing `# ...` is passed to the instruction as arguments and breaks the build.

```dockerfile
FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY models/ ./models/
# Default data so a plain `docker run` works; compose mounts ./data over it
COPY data/ ./data/
ENV DATA_DIR=/srv/data
EXPOSE 8000
# One worker: the catalogue lives in RAM and requests are cheap
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 11.8 `docker-compose.yml`

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/srv/data:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 5s
      timeout: 3s
      retries: 5
```

### 11.9 `run.sh` (no-Docker start)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "ERROR: $PY not found. Install Python 3.9+." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "ERROR: Python 3.9+ required." >&2; exit 1; }

if "$PY" -m venv .venv >/dev/null 2>&1 && [ -x .venv/bin/python ]; then
  RUN_PY=.venv/bin/python
  "$RUN_PY" -m pip install -q --upgrade pip
  "$RUN_PY" -m pip install -q -r requirements.txt
else
  echo "venv unavailable; installing packages for the current user instead." >&2
  RUN_PY="$PY"
  "$PY" -m pip install -q --user -r requirements.txt \
    || "$PY" -m pip install -q --user --break-system-packages -r requirements.txt
fi

exec "$RUN_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Never `source` the venv's `activate` script (it can fail under `set -u`); call `.venv/bin/python` directly.

### 11.10 `Makefile` (recipe lines start with a TAB)

```makefile
.PHONY: run test docker
run:
	bash run.sh
test:
	python3 -m pytest -q
docker:
	docker compose up --build
```

### 11.11 README commands

- **Start (primary):** `docker compose up --build` (older Docker: `docker-compose up --build`)
- **Start without Docker:** `bash run.sh`
- **Tests:** `bash run.sh` once to install, then `.venv/bin/python -m pytest -q` (or `make test`)

---

## 12. Testing strategy (all offline)

`tests/conftest.py` provides `make_data(tmp_path, bom_rows, master_rows, service_rows)` that writes the three CSVs and returns the directory, and `build(dir, root)` that returns the catalogue.

### 12.1 `test_loader.py` — value helpers
- Every `norm_pn` assertion in 4.1.
- Every row of the `parse_int` table in 4.3.
- `parse_flag` for each YES/NO value, plus `"?"` and `"Y/N"` → `("N", False)`.
- `rev_key`: `"" < "A" < "B" < "Z" < "AA"`.

### 12.2 `test_loader.py` — reading files
- Header variants (`Part Number`, `part-number`, BOM, quotes).
- Ragged rows padded and trimmed; blank lines skipped.
- cp1252-encoded file reads correctly.
- NUL byte removed.
- Missing file → `StartupError`; missing required column → `StartupError` naming the column.
- Missing `category`/`unit_cost` columns → no error; garbage `unit_cost` → row kept.

### 12.3 `test_loader.py` — validation and conflicts
- Validate-then-dedup: an invalid first row followed by a valid duplicate keeps the edge.
- Conflicting quantities: `[2, 3, 3]` → 3; `[2, 3]` → 2 (first).
- Revisions: `A,B` → B; `B,AA` → AA; blank + `A` → A; tie keeps first.
- Service: every row of the tables in 5.3 and 6.3. Y+N → not replaceable. Y rows with only invalid ranges → replaceable, no serial matches.
- Aliases: master `AS40003` with BOM `AS-40003` → resolved; two BOM spellings sharing a loose key → nothing merged.

### 12.4 `test_catalogue.py`
- Direct cycle, indirect cycle, cycle reachable via two parents, several cycles, cycle touching the root.
- Each removed edge appears once in `removed_edges`; result acyclic; reachable set unchanged.
- Exact cycle-rule cases (each must remove exactly the listed edge):

| Case | Graph (root first) | Must remove |
|---|---|---|
| Fastener entered first | `R→A, R→X, A→F, A→Q, X→Y, X→Z, Y→F, Y→W, F→X` | `F→X` |
| Single-child assembly on the cycle | `R→A, R→B, A→M, M→F, B→F, F→A` | `F→A` (not `M→F`) |
| Guard (cut would drop parts) | `R→U, U→V, V→U, V→X` | `V→U`; `V` and `X` stay in the machine |
| Appendix Q plus a bad edge | Appendix Q edges plus `FA-9→AS-2 ×1` | `FA-9→AS-2` |
| Two real assemblies (ambiguous) | `R→A, R→B, A→B, A→P, B→A, B→Q` | `B→A` (plain DFS back edge, deterministic) |
- Orphan assembly whose child is in the machine → orphan never in `parents`, child's total excludes it.
- Root absent from BOM → catalogue is only the root.
- Root paths `[[root]]`; root total 1.
- 2,000-level chain: no recursion error; last part total equals the product of quantities; one path of length 2,001.

### 12.5 `test_worked_example.py` (Appendix Q, root `AS-1`)

| # | Check |
|---|---|
| 1 | `parts == 4` |
| 2 | `ready == 2` |
| 3 | `missing == 1` |
| 4 | `not_replaceable == 1` |
| 5 | FA-9 `total_quantity == 10` |
| 6 | FA-9 `revision == "B"` |
| 7 | FA-9 paths `== [["AS-1","AS-2","FA-9"], ["AS-1","FA-9"]]` |
| 8 | serial 2500 `applicable_parts == 2` |

Also: FA-9 `parents == ["AS-1", "AS-2"]`, `children == []`.

### 12.6 `test_real_data.py` (visible `data/` folder — baseline)

| Check | Expected |
|---|---|
| `/api/validation` | `{"parts": 875, "ready": 483, "missing": 25, "not_replaceable": 367}` |
| `catalogue.removed_edges` | exactly `[("AS-40209", "AS-40002", 1)]`, rule `back_edge` |
| `AS-40002` parents | `["AS-40001"]` |
| `AS-40209` children | `EL-10335 ×1`, `FA-30022 ×3` (no `AS-40002`) |
| `FA-30019` | total 178, 22 parents, 22 paths |
| `FA-30022` | total 66, 12 parents, `AS-40210` not among them |
| `AS-40000` | status `not_replaceable`, total 1 |
| `EL-10024` | status `missing`, description and revision `None` |
| Sum of path counts | 1,242 (so paths are precomputed) |

### 12.7 `test_cycles_injected.py`
Take the visible BOM with its cycle removed. For each seed in `(11, 12, 13)`, run 1,000 trials with `random.Random(seed)`: pick a non-root reachable part `u` (from the sorted list of parts), pick one of its ancestors `v` (not the root, from the sorted list), add edge `u → v` with quantity 1. Assert the removed set equals the injected set.

| Injected bad edges per trial | Required score per seed |
|---|---|
| 1 | 1000/1000 |
| 3 | 1000/1000 |
| 5 (overlapping cycles become ambiguous) | at least 995/1000 |

Print the plain-DFS score alongside for comparison (expected about 976/1000 for one edge and 911/1000 for three).

### 12.8 `test_safety_nets.py`
Force each safety net and assert the service still builds:
- `choose_cut` raising → falls back to the plain back edge, rule recorded.
- Iteration cap reached (monkeypatch cap to 0 on a cyclic graph) → fallback strips back edges, graph acyclic.
- `topo_order` given a cyclic graph → fallback runs, catalogue still built.
- Global exception handler → a route forced to raise returns JSON 500.

### 12.9 `test_invariance.py`
Copy the visible CSVs into `tmp_path`, apply one corruption, rebuild, and assert the catalogue equals the clean baseline (every `part_info` entry, every path list, validation counts):

lowercase part numbers · leading/trailing spaces · NBSP inside part numbers · zero-width characters · full-width letters · en dashes · quantities as `3.0` · serial bounds as `1000.0` · `Yes`/`No` flags · every row duplicated · rows shuffled (fixed seed) · header capitalised and spaced · CRLF ↔ LF · cp1252 encoding · repeated header line in the middle · extra unknown column.

Corruptions that **should** change the answer each get an exact expected-diff test: an invalid quantity drops that edge; a reversed range fits no serial; `TBD` flag → `not_replaceable`; Y+N conflict → `not_replaceable`.

### 12.10 `test_random_crosscheck.py`
Seeds 0–199. Generate a random graph of 5–30 parts with duplicates, cycles, orphans and invalid rows. Compare the catalogue against an independently written brute-force reference (recursive path enumeration over the **same cleaned, cycle-removed** edges) for totals, sorted paths, parents and children.

### 12.11 `test_api.py` (TestClient)
- Response shapes and field order for every endpoint.
- 404 (never 422) for unknown parts on both part endpoints.
- `/api/parts/fa-30019`, `/api/parts/%20as-40003%20`, `/api/parts/fa30019` (loose match) → 200 with canonical `part_number`.
- `%23` and `%2F` reach the handler (use a fixture with `GF#1` and `AB/2`).
- Serial `2500`, `0`, `-5`, `+7`, `007` → 200. `abc`, `2500.5`, `2500.0`, `1e3` → 400. A 1,000-digit serial → 200; a 5,000-digit serial → 400.
- `/health` → `{"status": "ok"}`; `/` returns HTML.

### 12.12 `test_performance.py`

Record nodes, edges, maximum depth, expected path count, and the measured time in the test output.

| Test | Shape | Pass condition |
|---|---|---|
| Real data | all endpoints for every part | each request < 0.5 s |
| Deep chain | 2,000 levels | build < 5 s; requests < 0.5 s |
| Diamond lattice | 16 layers of 2-way splits = 65,536 paths to the bottom part | build < 10 s; paths request < 1 s |
| Large lattice (documented limit) | 20 layers = 1,048,576 paths | lazy mode used; record the time; marked `xfail`-safe, documented in NOTES.md |

---

## 13. Implementation phases and commits

Each phase ends with all tests so far passing and one commit with the message shown.

### Phase 0 — scaffold
**Files:** structure from 11.3 (`app/`, `models/`, `data/`, `tests/` with empty modules and `__init__.py` files), `.gitignore`, `.gitattributes`, `.dockerignore`, `requirements.txt`, `app/config.py`, `data/` with the visible CSVs, this `PRODUCT.md`.
**Done when:** `pip install -r requirements.txt` succeeds; `python -c "import app.config, models"` works from the repository root; `pytest` runs (0 tests).
**Commit:** `chore: project scaffold, config and pinned requirements`

### Phase 1 — value parsers
**Files:** `app/loader.py` (block 1: value helpers), `tests/test_loader.py` (12.1).
**Done when:** every test in 12.1 passes.
**Commit:** `feat: part-number, integer, flag and revision parsers`

### Phase 2 — safe CSV reader
**Files:** `models/records.py` (`Row` only for now), `models/__init__.py`, `app/loader.py` (block 2: `read_csv`), `tests/test_loader.py` (12.2), `tests/conftest.py`.
**Done when:** 12.2 passes.
**Commit:** `feat: crash-proof CSV reader`

### Phase 3 — row validation and conflict resolution
**Files:** `models/records.py` (add `BomEdge`, `MasterRow`, `ServiceRow`, `ServiceDecision`), `app/loader.py` (blocks 3–4), `tests/test_loader.py` (12.3).
**Done when:** 12.3 passes.
**Commit:** `feat: validate rows, dedup BOM, select revisions, resolve service flags and aliases`

### Phase 4 — catalogue core
**Files:** `app/catalogue.py`, `tests/test_catalogue.py`, `tests/test_worked_example.py`.
**Done when:** 12.4 and 12.5 pass.
**Commit:** `feat: reachability, cycle removal, topological DP totals, paths and statuses`

### Phase 5 — real data baseline
**Files:** `tests/test_real_data.py`.
**Done when:** 12.6 passes.
**Commit:** `test: real-data baseline`

### Phase 6 — cycle robustness and safety nets
**Files:** `tests/test_cycles_injected.py`, `tests/test_safety_nets.py` (plus any fixes they reveal).
**Done when:** 12.7 meets every threshold in its table and 12.8 passes.
**Commit:** `test: injected-cycle accuracy and safety-net coverage`

### Phase 7 — API, models and page
**Files:** `models/responses.py`, `models/__init__.py` (re-export responses), `app/main.py`, `app/static/index.html`, `tests/test_api.py`.
**Done when:** 12.11 passes; `uvicorn app.main:app` serves the page and every endpoint manually.
**Commit:** `feat: FastAPI endpoints, response models and test page`

### Phase 8 — deployment
**Files:** `Dockerfile`, `docker-compose.yml`, `run.sh`, `Makefile`.
**Done when:**
- In a **fresh clone** in a new directory: `docker compose up --build` → `curl localhost:8000/health` returns ok.
- `docker build -t parts . && docker run -p 8000:8000 parts` works (this also proves `models/` is copied into the image).
- `bash run.sh` works in a fresh clone.
- Replacing `data/` with the Appendix Q example files (and `ROOT_PN=AS-1`) changes the answers with no code change.
**Commit:** `build: Docker, compose and no-Docker run script`

### Phase 9 — robustness and performance tests
**Files:** `tests/test_invariance.py`, `tests/test_random_crosscheck.py`, `tests/test_performance.py`.
**Done when:** 12.9, 12.10 and 12.12 pass.
**Commit:** `test: invariance, randomised cross-check and performance`

### Phase 10 — documentation
**Files:** `README.md`, `DATA.md`, `NOTES.md`, `AI.md`.
- `README.md`: what it is; the one start command and the alternative; how to run tests; endpoint list with examples; configuration table.
- `DATA.md`: data findings and every rule with its alternative and reason; must agree with this file.
- `NOTES.md` (one page max): key decisions, what was cut (database, path cache, interval tree, using `category`), known limitations (ambiguous cycles between two real assemblies; exponential path counts), what to do next.
- `AI.md`: every AI tool used and what for.
**Done when:** a final fresh-clone run of Phase 8's checks passes and `pytest` is green.
**Commit:** `docs: README, DATA, NOTES and AI`

---

## 14. Key design decisions (summary)

| Decision | Choice | Reason |
|---|---|---|
| Fatal errors | Only a missing file or required column | Bad rows must never stop the service |
| Part numbers | NFKC, remove format chars, unify dashes, remove all whitespace, uppercase; keep separators | "However a system types it", without merging distinct parts |
| Separator variants | Map to the BOM spelling only when the loose key matches exactly one BOM part | Adapts to hidden data; never merges two real parts |
| Integers | Accept `3`, `3.0`, `1,000`; null tokens are blank; reject `2.5`, `1e3`, `1_0` | `3.0` has one meaning; rejecting it would delete a subtree |
| Invalid quantity | Drop that row | Inventing a quantity orders the wrong count |
| Validate vs dedup | Validate every row first | An invalid row cannot hide a valid duplicate |
| Conflicting quantities | Most common; tie → first | Independent of row order where possible |
| Revision order | `(length, value)` | Documented assumption for multi-letter revisions |
| Blank description | `""` from the latest revision | Older text describes a superseded part |
| Y/N vocabulary | Accept Yes/True/1; unknown → N | Unclear values never make a part `ready` |
| Y/N conflict | **N wins** | Contradictory data → safe mistake |
| Invalid or reversed range | Fits no serial | Junk never becomes "fits everything" |
| One-sided range | Open-ended | Data uses `9999` to mean "onwards" |
| Orphans | Excluded entirely | "Not in the machine = not in the catalogue" |
| Cycle removal | DFS back edge, preferring the edge out of a fake container (part with nothing outside the cycle, contained by a real assembly); guarded; capped; fallback | 1000/1000 on injected single and triple bad edges; never loses parts; never crashes |
| Topological order | Kahn's algorithm | Doubles as a runtime acyclicity check |
| Totals | DP along topological order | Exact, linear, no path explosion |
| Paths | Precompute if ≤ 200,000 in total, else on request; no cache | No stale cache; contract needs complete lists |
| URL part lookup | `norm_pn`, then unique loose-key match | Matches parts "however they are typed" |
| Serial parsing | `[+-]?[0-9]+`, `int()` in try/except; no length cap | Rejects non-whole numbers; never 500 |
| Response models | Types only, no constraints | A data quirk must not become a 500 |
| Storage | In-memory `Catalogue` built at startup; no database | Small data, sub-millisecond lookups, nothing to install |
| Runtime | One uvicorn worker | Catalogue in RAM; avoids duplicate builds |
| Start command | `docker compose up --build`; `bash run.sh` fallback with venv → `--user` fallback | Works with or without Docker on a clean machine |

---

## 15. Success criteria

- [ ] All 8 Appendix Q checks pass (12.5)
- [ ] Real-data baseline matches exactly (12.6)
- [ ] Injected-cycle test meets every threshold in 12.7
- [ ] Every safety net exercised and the service still starts (12.8)
- [ ] Every invariance corruption leaves answers unchanged (12.9)
- [ ] Random cross-check passes for seeds 0–199 (12.10)
- [ ] Unknown part → 404 (never 422); non-whole serial → 400; no 500 for any input
- [ ] `docker compose up --build`, plain `docker run`, and `bash run.sh` each serve `/health` on port 8000 from a fresh clone
- [ ] Replacing `data/` changes answers with no code change
- [ ] Every request under 1 second on the real data
- [ ] `pytest` passes offline
- [ ] README, DATA.md, NOTES.md (one page), AI.md complete, and consistent with this file
