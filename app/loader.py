"""Stages 1-3: read CSVs, clean values, validate rows, resolve conflicts (PRODUCT.md sections 3-6)."""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from models import BomEdge, MasterRow, Row, ServiceDecision, ServiceRow


class StartupError(Exception):
    """The only exception allowed to stop startup: a missing file or required column (section 3.3)."""


# ---------------------------------------------------------------------------
# Block 1: value helpers (PRODUCT.md section 4)
# ---------------------------------------------------------------------------

# Dash look-alikes -> "-": hyphen, non-breaking hyphen, figure dash, en dash, em dash,
# horizontal bar, minus sign, small em dash, small hyphen-minus, full-width hyphen-minus.
DASHES = dict.fromkeys(
    map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-"
)


def norm_pn(v: str | None) -> str:
    """Canonical part number. Keeps separators (- _ # /); see section 4.1."""
    v = unicodedata.normalize("NFKC", v or "")                       # full-width -> ASCII, NBSP -> space
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Cf")  # zero-width, joiners, BOM, soft hyphen
    v = v.translate(DASHES)                                          # dash look-alikes -> "-"
    v = "".join(v.split())                                           # remove ALL whitespace, incl. internal
    return v.upper()


def loose_key(pn: str) -> str:
    """Letters and digits only. For alias matching and URL fallback; never an output value."""
    return re.sub(r"[^A-Z0-9]", "", pn)   # pn is already norm_pn'd


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name


BLANK = _Sentinel("BLANK")
INVALID = _Sentinel("INVALID")

NULL_TOKENS = {"", "NAN", "NULL", "NONE", "N/A", "NA", "-"}
_INT = re.compile(r"[+-]?[0-9]+")          # [0-9], never \d (which matches non-ASCII digits)
_INT_DEC = re.compile(r"([+-]?[0-9]+)\.0+")


def parse_int(v):
    """Whole number -> int; null token -> BLANK; anything else -> INVALID (section 4.3)."""
    s = (v or "").strip().replace(",", "")
    if s.upper() in NULL_TOKENS:
        return BLANK
    if _INT.fullmatch(s):
        return int(s)
    m = _INT_DEC.fullmatch(s)
    if m:
        return int(m.group(1))
    return INVALID


YES = {"Y", "YES", "TRUE", "T", "1"}
NO = {"N", "NO", "FALSE", "F", "0", ""}


def parse_flag(v):
    """Replaceable flag -> ("Y" | "N", known). Unknown values are treated as N (section 4.4)."""
    s = (v or "").strip().upper()
    if s in YES:
        return "Y", True
    if s in NO:
        return "N", True
    return "N", False          # unknown value: treated as N


def norm_rev(v: str | None) -> str:
    return (v or "").strip().upper()


def rev_key(r: str) -> tuple[int, str]:
    return (len(r), r)      # "" < "A" < "B" < "Z" < "AA"


# ---------------------------------------------------------------------------
# Block 2: reading files safely (PRODUCT.md section 3.1)
# ---------------------------------------------------------------------------

# The csv module's default 131,072-character cell limit raises csv.Error on one oversized
# cell, which would stop startup. Raise it to the largest value the platform's C long
# accepts (2**31 - 1 on Windows, where sys.maxsize overflows).
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def canon_header(h: str) -> str:
    h = h.replace("\ufeff", "").strip().strip('"').strip().lower()
    return re.sub(r"[\s\-]+", "_", h)


def _decode(data: bytes) -> str:
    data = data.replace(b"\x00", b"")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_csv(path: Path, required_columns: Iterable[str]) -> list[Row]:
    """Read one CSV into Rows keyed by canonical header names.

    Raises StartupError only for a missing file or a missing required column."""
    path = Path(path)
    name = path.name
    if not path.is_file():
        raise StartupError(f"{name}: file not found at {path}")

    reader = csv.reader(io.StringIO(_decode(path.read_bytes())))

    header: list[str] | None = None
    rows: list[Row] = []
    while True:
        lineno = reader.line_num + 1          # first physical line of the next record
        try:
            cells = next(reader)
        except StopIteration:
            break
        if all(not c.strip() for c in cells):
            continue
        if header is None:
            header = [canon_header(c) for c in cells]
            missing = set(required_columns) - set(header)
            if missing:
                raise StartupError(
                    f"{name}: missing required column(s) {sorted(missing)}; found {header}"
                )
            continue
        width = len(header)
        cells = (cells + [""] * width)[:width]
        rows.append(Row(line=lineno, values=dict(zip(header, cells))))

    if header is None:                        # empty file: every required column is missing
        raise StartupError(
            f"{name}: missing required column(s) {sorted(set(required_columns))}; found []"
        )
    return rows


# ---------------------------------------------------------------------------
# Block 3: per-file row validation (PRODUCT.md section 5)
# Every row is handled inside try/except: an unexpected error skips that row only (3.2).
# ---------------------------------------------------------------------------

BOM_COLUMNS = ("parent_pn", "child_pn", "quantity")
MASTER_COLUMNS = ("part_number", "revision", "description")
SERVICE_COLUMNS = ("part_number", "field_replaceable", "serial_from", "serial_to")


def validate_bom(rows: list[Row]) -> list[BomEdge]:
    out = []
    for r in rows:
        try:
            parent = norm_pn(r.values["parent_pn"])
            child = norm_pn(r.values["child_pn"])
            if not parent or not child or parent == child:
                continue
            q = parse_int(r.values["quantity"])
            if not isinstance(q, int) or q <= 0:
                continue
            out.append(BomEdge(parent, child, q, r.line))
        except Exception:
            continue
    return out


def validate_master(rows: list[Row]) -> list[MasterRow]:
    out = []
    for r in rows:
        try:
            pn = norm_pn(r.values["part_number"])
            if not pn:
                continue
            out.append(MasterRow(pn, norm_rev(r.values["revision"]), (r.values["description"] or "").strip(), r.line))
        except Exception:
            continue
    return out


def _serial_range(a, b) -> tuple[int | None, int | None, bool]:
    """(lo, hi, range_valid) from two parse_int results (table in 5.3)."""
    if a is INVALID or b is INVALID:
        return None, None, False
    lo = None if a is BLANK else a
    hi = None if b is BLANK else b
    if lo is not None and hi is not None and lo > hi:
        return None, None, False
    return lo, hi, True


def validate_service(rows: list[Row]) -> list[ServiceRow]:
    out = []
    for r in rows:
        try:
            pn = norm_pn(r.values["part_number"])
            if not pn:
                continue
            flag, _ = parse_flag(r.values["field_replaceable"])
            lo, hi, valid = _serial_range(parse_int(r.values["serial_from"]), parse_int(r.values["serial_to"]))
            out.append(ServiceRow(pn, flag, lo, hi, valid, r.line))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Block 4: conflict resolution and load_all (PRODUCT.md section 6)
# ---------------------------------------------------------------------------


def dedup_bom(edges: list[BomEdge]) -> dict[str, dict[str, int]]:
    """(6.1) Most common quantity per (parent, child); on a tie, the tied quantity seen first."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for e in sorted(edges, key=lambda e: e.line):
        groups[(e.parent, e.child)].append(e.qty)
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for (parent, child), qtys in groups.items():
        try:
            counts = Counter(qtys)
            best = max(counts.values())
            out[parent][child] = next(q for q in qtys if counts[q] == best)
        except Exception:
            continue
    return dict(out)


def select_revision(rows: list[MasterRow]) -> dict[str, str]:
    """(6.2) Highest rev_key; on a tie, the lowest line number."""
    best = max(sorted(rows, key=lambda r: r.line), key=lambda r: rev_key(r.rev))   # max keeps the first maximum
    return {"revision": best.rev, "description": best.description}


def decide_service(rows: list[ServiceRow]) -> ServiceDecision:
    """(6.3) Replaceable only if every row is Y; any N (or unknown flag) wins."""
    if not rows or any(r.flag != "Y" for r in rows):
        return ServiceDecision()
    rows = sorted(rows, key=lambda r: r.line)
    return ServiceDecision(
        replaceable=True,
        unrestricted=any(r.range_valid and r.lo is None and r.hi is None for r in rows),
        ranges=[(r.lo, r.hi) for r in rows if r.range_valid and (r.lo is not None or r.hi is not None)],
    )


def alias_map(keys: Iterable[str], bom_keys: set[str]) -> dict[str, str]:
    """(6.4) Non-BOM spelling -> BOM spelling, when exactly one BOM part shares its loose key."""
    bom_loose: dict[str, set[str]] = defaultdict(set)
    for k in bom_keys:
        bom_loose[loose_key(k)].add(k)
    out = {}
    for k in keys:
        if k in bom_keys:
            continue
        matches = bom_loose.get(loose_key(k), set())
        if len(matches) == 1:
            out[k] = next(iter(matches))
    return out


def resolve_master(rows: list[MasterRow], bom_keys: set[str]) -> dict[str, dict[str, str]]:
    """6.2 + 6.4. An exact BOM-spelled entry beats an alias; several aliases with no exact
    entry are merged and the revision is selected again over all their rows."""
    groups: dict[str, list[MasterRow]] = defaultdict(list)
    for r in rows:
        groups[r.pn].append(r)
    aliases = alias_map(groups, bom_keys)
    merged: dict[str, list[MasterRow]] = defaultdict(list)
    for pn, group in groups.items():
        target = aliases.get(pn, pn)
        if target != pn and target in groups:
            continue                      # exact key's entry wins
        merged[target].extend(group)
    out = {}
    for pn, group in merged.items():
        try:
            out[pn] = select_revision(group)
        except Exception:
            continue
    return out


def resolve_service(rows: list[ServiceRow], bom_keys: set[str]) -> dict[str, ServiceDecision]:
    """6.3 + 6.4. Alias rows are re-keyed to the BOM spelling and merged before deciding."""
    aliases = alias_map({r.pn for r in rows}, bom_keys)
    groups: dict[str, list[ServiceRow]] = defaultdict(list)
    for r in rows:
        groups[aliases.get(r.pn, r.pn)].append(r)
    out = {}
    for pn, group in groups.items():
        try:
            out[pn] = decide_service(group)
        except Exception:
            continue
    return out


def load_all(data_dir: Path) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, str]], dict[str, ServiceDecision]]:
    """Stages 1-3: returns (edges, master, service). Raises only StartupError."""
    data_dir = Path(data_dir)
    bom_rows = read_csv(data_dir / "bom.csv", BOM_COLUMNS)
    master_rows = read_csv(data_dir / "parts_master.csv", MASTER_COLUMNS)
    service_rows = read_csv(data_dir / "service_parts.csv", SERVICE_COLUMNS)

    edges = dedup_bom(validate_bom(bom_rows))
    bom_keys = set(edges) | {c for children in edges.values() for c in children}
    master = resolve_master(validate_master(master_rows), bom_keys)
    service = resolve_service(validate_service(service_rows), bom_keys)
    return edges, master, service
