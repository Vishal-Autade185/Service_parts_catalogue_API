"""PRODUCT.md 12.9: corrupt a copy of the visible data in one way, rebuild, and compare.

Corruptions the spec handles must leave every answer unchanged; the ones that should change
an answer get an exact expected-diff test."""
from __future__ import annotations

import csv
import io
import random

import pytest

from app.config import DATA_DIR
from tests.conftest import build

ROOT = "AS-40000"
FILES = ("bom.csv", "parts_master.csv", "service_parts.csv")
PN_COLS = {"bom.csv": (0, 1), "parts_master.csv": (0,), "service_parts.csv": (0,)}
NBSP, ZWSP, EN_DASH = "\N{NO-BREAK SPACE}", "\N{ZERO WIDTH SPACE}", "\N{EN DASH}"


def read_tables() -> dict[str, list[list[str]]]:
    """The visible CSVs as lists of rows; row 0 is the header."""
    return {f: list(csv.reader(io.StringIO((DATA_DIR / f).read_text(encoding="utf-8-sig")))) for f in FILES}


def write_tables(d, tables, encoding="utf-8", newline="\r\n"):
    for f, rows in tables.items():
        buf = io.StringIO()
        csv.writer(buf, lineterminator=newline).writerows(rows)
        (d / f).write_bytes(buf.getvalue().encode(encoding))
    return d


def snapshot(cat):
    """Everything the API can answer."""
    return {
        "counts": cat.counts,
        "removed": cat.removed_edges,
        "parts": cat.part_info,
        "paths": {pn: cat.paths(pn) for pn in cat.part_info},
        "serials": {s: cat.applicable(s) for s in (-1, 0, 1, 999, 1000, 2500, 5000, 9999, 10**6)},
    }


@pytest.fixture(scope="module")
def baseline():
    return snapshot(build(DATA_DIR, ROOT))


def map_pns(tables, fn):
    for f, cols in PN_COLS.items():
        for row in tables[f][1:]:
            for c in cols:
                row[c] = fn(row[c])
    return tables


def map_col(tables, f, cols, fn):
    for row in tables[f][1:]:
        for c in cols:
            row[c] = fn(row[c])
    return tables


def full_width(s: str) -> str:
    return "".join(chr(ord(ch) + 0xFEE0) if ch.isalnum() and ch.isascii() else ch for ch in s)


def duplicate_rows(tables):
    return {f: [rows[0]] + [r for r in rows[1:] for _ in range(2)] for f, rows in tables.items()}


def shuffle_rows(tables):
    rng = random.Random(7)
    out = {}
    for f, rows in tables.items():
        body = rows[1:]
        rng.shuffle(body)
        out[f] = [rows[0]] + body
    return out


def spaced_headers(tables):
    for rows in tables.values():
        rows[0] = [f"  {h.replace('_', ' ').title()} " for h in rows[0]]
    return tables


def repeat_header(tables):
    for rows in tables.values():
        rows.insert(len(rows) // 2, list(rows[0]))
    return tables


def extra_column(tables):
    for rows in tables.values():
        rows[0].append("notes")
        for i, row in enumerate(rows[1:]):
            row.append(f"note {i}, see sheet")
    return tables


CORRUPTIONS = {
    "lowercase part numbers": lambda t: map_pns(t, str.lower),
    "leading/trailing spaces": lambda t: map_pns(t, lambda v: f"  {v} "),
    "NBSP inside part numbers": lambda t: map_pns(t, lambda v: v.replace("-", "-" + NBSP)),
    "zero-width characters": lambda t: map_pns(t, lambda v: v[:2] + ZWSP + v[2:]),
    "full-width letters": lambda t: map_pns(t, full_width),
    "en dashes": lambda t: map_pns(t, lambda v: v.replace("-", EN_DASH)),
    "quantities as 3.0": lambda t: map_col(t, "bom.csv", (2,), lambda v: f"{v}.0"),
    "serial bounds as 1000.0": lambda t: map_col(t, "service_parts.csv", (2, 3), lambda v: f"{v}.0" if v else v),
    "Yes/No flags": lambda t: map_col(t, "service_parts.csv", (1,), lambda v: {"Y": "Yes", "N": "No"}.get(v, v)),
    "every row duplicated": duplicate_rows,
    "rows shuffled": shuffle_rows,
    "header capitalised and spaced": spaced_headers,
    "repeated header line": repeat_header,
    "extra unknown column": extra_column,
}


def test_clean_round_trip(tmp_path, baseline):
    assert snapshot(build(write_tables(tmp_path, read_tables()), ROOT)) == baseline


@pytest.mark.parametrize("name", list(CORRUPTIONS))
def test_corruption_leaves_answers_unchanged(tmp_path, baseline, name):
    tables = CORRUPTIONS[name](read_tables())
    assert snapshot(build(write_tables(tmp_path, tables), ROOT)) == baseline


def test_lf_line_endings(tmp_path, baseline):
    assert b"\r\n" in (DATA_DIR / "bom.csv").read_bytes()          # visible data is CRLF
    assert snapshot(build(write_tables(tmp_path, read_tables(), newline="\n"), ROOT)) == baseline


def test_cp1252_encoding(tmp_path, baseline):
    tables = map_pns(read_tables(), lambda v: v.replace("-", EN_DASH))   # en dash is byte 0x96 in cp1252
    write_tables(tmp_path, tables, encoding="cp1252")
    with pytest.raises(UnicodeDecodeError):
        (tmp_path / "bom.csv").read_bytes().decode("utf-8")
    assert snapshot(build(tmp_path, ROOT)) == baseline


# ---------------------------------------------------------------------------
# Corruptions that must change the answer, each by an exact expected diff
# ---------------------------------------------------------------------------


def find_service_part(tables, baseline, want_range: bool):
    """A ready part with exactly one service row, Y, with or without a closed range."""
    rows = tables["service_parts.csv"][1:]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    for i, r in enumerate(rows, start=1):
        pn, flag, lo, hi = r
        if counts[pn] != 1 or flag != "Y" or baseline["parts"].get(pn, {}).get("status") != "ready":
            continue
        if want_range and lo and hi and int(lo) < int(hi):
            return i, pn
        if not want_range and not lo and not hi:
            return i, pn
    raise AssertionError("no suitable service row in the visible data")


def only_status_changed(before, after, pn):
    assert after["parts"][pn]["status"] == "not_replaceable"
    assert {k: v for k, v in after["parts"].items() if k != pn} == \
        {k: v for k, v in before["parts"].items() if k != pn}
    assert {k: v for k, v in after["parts"][pn].items() if k != "status"} == \
        {k: v for k, v in before["parts"][pn].items() if k != "status"}
    c = dict(before["counts"])
    c["ready"] -= 1
    c["not_replaceable"] += 1
    assert after["counts"] == c


def test_invalid_quantity_drops_that_edge(tmp_path, baseline):
    tables = read_tables()
    bom = tables["bom.csv"]
    pairs = [(r[0], r[1]) for r in bom[1:]]
    removed = {(p, c) for p, c, _ in baseline["removed"]}
    i = next(i for i, r in enumerate(bom[1:], start=1)
             if pairs.count((r[0], r[1])) == 1 and r[0] in baseline["parts"] and (r[0], r[1]) not in removed
             and len(baseline["parts"][r[1]]["parents"]) > 1)
    parent, child = bom[i][0], bom[i][1]

    bad, deleted = tmp_path / "bad", tmp_path / "deleted"
    bad.mkdir()
    deleted.mkdir()
    bom[i][2] = "abc"
    after = snapshot(build(write_tables(bad, tables), ROOT))
    del bom[i]
    expected = snapshot(build(write_tables(deleted, tables), ROOT))

    assert after == expected                                         # invalid row == row not there at all
    assert parent not in after["parts"][child]["parents"]
    assert child not in [c["part_number"] for c in after["parts"][parent]["children"]]
    assert after["parts"][child]["total_quantity"] < baseline["parts"][child]["total_quantity"]


def test_reversed_range_fits_no_serial(tmp_path, baseline):
    tables = read_tables()
    i, pn = find_service_part(tables, baseline, want_range=True)
    row = tables["service_parts.csv"][i]
    lo, hi = int(row[2]), int(row[3])
    row[2], row[3] = row[3], row[2]
    cat = build(write_tables(tmp_path, tables), ROOT)
    assert cat.part_info == baseline["parts"]                        # still ready
    base = build(DATA_DIR, ROOT)
    for s in (lo, (lo + hi) // 2, hi):
        assert cat.applicable(s) == base.applicable(s) - 1
    for s in (lo - 1, hi + 1):
        assert cat.applicable(s) == base.applicable(s)


def test_tbd_flag_makes_part_not_replaceable(tmp_path, baseline):
    tables = read_tables()
    i, pn = find_service_part(tables, baseline, want_range=False)
    tables["service_parts.csv"][i][1] = "TBD"
    after = snapshot(build(write_tables(tmp_path, tables), ROOT))
    only_status_changed(baseline, after, pn)
    assert all(after["serials"][s] == baseline["serials"][s] - 1 for s in baseline["serials"])


def test_y_and_n_conflict_makes_part_not_replaceable(tmp_path, baseline):
    tables = read_tables()
    i, pn = find_service_part(tables, baseline, want_range=False)
    tables["service_parts.csv"].append([pn, "N", "", ""])
    after = snapshot(build(write_tables(tmp_path, tables), ROOT))
    only_status_changed(baseline, after, pn)
