from __future__ import annotations

import pytest

from app.loader import (
    BLANK,
    INVALID,
    StartupError,
    canon_header,
    load_all,
    norm_pn,
    parse_flag,
    parse_int,
    read_csv,
    rev_key,
)
from models import ServiceDecision
from tests.conftest import MASTER_HEADER, make_data, write_csv

MASTER_REQUIRED = ("part_number", "revision", "description")
BOM_REQUIRED = ("parent_pn", "child_pn", "quantity")

# ---------------------------------------------------------------------------
# 12.1 Value helpers
# ---------------------------------------------------------------------------


def test_norm_pn_spec_assertions():
    assert norm_pn("GF\u200b48488") == "GF48488"          # zero-width space
    assert norm_pn("GF\u00a048488") == "GF48488"          # non-breaking space
    assert norm_pn(" fa-30013 ") == "FA-30013"
    assert norm_pn("\uff21\uff33-40000") == "AS-40000"    # full-width "AS"
    assert norm_pn("AS\u201340000") == "AS-40000"         # en dash
    assert norm_pn("AS 40000") == "AS40000"
    assert norm_pn("GF#48488") != norm_pn("GF-48488")
    assert norm_pn(None) == ""


@pytest.mark.parametrize(
    "value, expected",
    [
        ("3", 3),
        (" 3 ", 3),
        ("+3", 3),
        ("-5", -5),
        ("3.0", 3),
        ("1000.00", 1000),
        ("1,000", 1000),
    ],
)
def test_parse_int_integers(value, expected):
    result = parse_int(value)
    assert type(result) is int
    assert result == expected


@pytest.mark.parametrize("value", ["", "NULL", "N/A", "na", "NaN", "None", "-"])
def test_parse_int_blank(value):
    assert parse_int(value) is BLANK


@pytest.mark.parametrize("value", ["2.5", "abc", "1e3", "1_0", "3.0.0"])
def test_parse_int_invalid(value):
    assert parse_int(value) is INVALID


@pytest.mark.parametrize("value", ["Y", "YES", "TRUE", "T", "1", "y", " yes ", "True"])
def test_parse_flag_yes(value):
    assert parse_flag(value) == ("Y", True)


@pytest.mark.parametrize("value", ["N", "NO", "FALSE", "F", "0", "", "n", " no ", "False", None])
def test_parse_flag_no(value):
    assert parse_flag(value) == ("N", True)


@pytest.mark.parametrize("value", ["?", "Y/N"])
def test_parse_flag_unknown(value):
    assert parse_flag(value) == ("N", False)


def test_rev_key_order():
    revs = ["", "A", "B", "Z", "AA"]
    assert sorted(reversed(revs), key=rev_key) == revs
    for lower, higher in zip(revs, revs[1:]):
        assert rev_key(lower) < rev_key(higher)


# ---------------------------------------------------------------------------
# 12.2 Reading files
# ---------------------------------------------------------------------------


def _write_bytes(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Part Number", "part_number"),
        ("part-number", "part_number"),
        ("PART_NUMBER", "part_number"),
        ('"part_number"', "part_number"),
        ("\ufeffpart_number", "part_number"),
        ("  Part  -  Number  ", "part_number"),
    ],
)
def test_canon_header(raw, expected):
    assert canon_header(raw) == expected


def test_header_variants_are_recognised(tmp_path):
    data = '\ufeff"Part Number",Revision,description\r\nAB-1,A,Widget\r\n'.encode("utf-8")
    p = _write_bytes(tmp_path, "parts_master.csv", data)
    rows = read_csv(p, MASTER_REQUIRED)
    assert len(rows) == 1
    assert rows[0].values == {"part_number": "AB-1", "revision": "A", "description": "Widget"}


def test_hyphenated_header(tmp_path):
    p = _write_bytes(tmp_path, "bom.csv", b"parent-pn,Child PN,QUANTITY\nA,B,2\n")
    rows = read_csv(p, BOM_REQUIRED)
    assert rows[0].values == {"parent_pn": "A", "child_pn": "B", "quantity": "2"}


def test_ragged_rows_padded_and_trimmed(tmp_path):
    p = _write_bytes(tmp_path, "bom.csv", b"parent_pn,child_pn,quantity\nA,B\nC,D,3,extra,more\n")
    rows = read_csv(p, BOM_REQUIRED)
    assert [r.values for r in rows] == [
        {"parent_pn": "A", "child_pn": "B", "quantity": ""},
        {"parent_pn": "C", "child_pn": "D", "quantity": "3"},
    ]


def test_blank_lines_skipped_and_line_numbers_match_file(tmp_path):
    data = b"\n  \nparent_pn,child_pn,quantity\nA,B,1\n\n , , \nC,D,2\n"
    p = _write_bytes(tmp_path, "bom.csv", data)
    rows = read_csv(p, BOM_REQUIRED)
    assert [(r.line, r.values["parent_pn"]) for r in rows] == [(4, "A"), (7, "C")]


def test_quoted_fields_with_commas(tmp_path):
    data = b'part_number,revision,description\nAB-1,A,"Bolt, M6 x 20"\n'
    p = _write_bytes(tmp_path, "parts_master.csv", data)
    assert read_csv(p, MASTER_REQUIRED)[0].values["description"] == "Bolt, M6 x 20"


def test_cp1252_file_reads_correctly(tmp_path):
    desc = "Caf\u00e9 \u2013 50\u00b0 seal"            # e-acute, en dash, degree sign
    data = f"part_number,revision,description\nAB-1,A,{desc}\n".encode("cp1252")
    p = _write_bytes(tmp_path, "parts_master.csv", data)
    rows = read_csv(p, MASTER_REQUIRED)
    assert rows[0].values["description"] == desc


def test_nul_bytes_removed(tmp_path):
    data = b"parent_pn,child_pn,quantity\nA\x00S-1,B\x00,\x002\n"
    p = _write_bytes(tmp_path, "bom.csv", data)
    assert read_csv(p, BOM_REQUIRED)[0].values == {"parent_pn": "AS-1", "child_pn": "B", "quantity": "2"}


def test_utf16_style_nul_padding_does_not_crash(tmp_path):
    data = "parent_pn,child_pn,quantity\nA,B,1\n".encode("utf-16-le")
    p = _write_bytes(tmp_path, "bom.csv", data)
    assert read_csv(p, BOM_REQUIRED)[0].values == {"parent_pn": "A", "child_pn": "B", "quantity": "1"}


def test_oversized_cell_does_not_crash(tmp_path):
    huge = "x" * 500_000                                  # well above csv's default 131,072 limit
    data = f'part_number,revision,description\nAB-1,A,"{huge}"\nAB-2,B,ok\n'.encode("utf-8")
    p = _write_bytes(tmp_path, "parts_master.csv", data)
    rows = read_csv(p, MASTER_REQUIRED)
    assert [r.values["part_number"] for r in rows] == ["AB-1", "AB-2"]
    assert len(rows[0].values["description"]) == 500_000


def test_repeated_header_is_returned_as_a_data_row(tmp_path):
    data = b"parent_pn,child_pn,quantity\nA,B,1\nparent_pn,child_pn,quantity\nC,D,2\n"
    p = _write_bytes(tmp_path, "bom.csv", data)
    rows = read_csv(p, BOM_REQUIRED)
    assert [r.values["parent_pn"] for r in rows] == ["A", "parent_pn", "C"]


def test_missing_file_raises_startup_error(tmp_path):
    with pytest.raises(StartupError, match=r"bom\.csv: file not found"):
        read_csv(tmp_path / "bom.csv", BOM_REQUIRED)


def test_missing_required_column_names_it(tmp_path):
    p = _write_bytes(tmp_path, "bom.csv", b"parent_pn,qty\nA,1\n")
    with pytest.raises(StartupError) as exc:
        read_csv(p, BOM_REQUIRED)
    msg = str(exc.value)
    assert msg.startswith("bom.csv: missing required column(s)")
    assert "child_pn" in msg and "quantity" in msg


def test_empty_file_raises_startup_error(tmp_path):
    p = _write_bytes(tmp_path, "bom.csv", b"")
    with pytest.raises(StartupError, match="missing required column"):
        read_csv(p, BOM_REQUIRED)


def test_optional_columns_may_be_absent(tmp_path):
    p = write_csv(tmp_path / "parts_master.csv", MASTER_REQUIRED, [("AB-1", "A", "Widget")])
    rows = read_csv(p, MASTER_REQUIRED)
    assert rows[0].values == {"part_number": "AB-1", "revision": "A", "description": "Widget"}


def test_garbage_unit_cost_row_kept(tmp_path):
    p = write_csv(
        tmp_path / "parts_master.csv",
        MASTER_HEADER,
        [("AB-1", "A", "Widget", "???", "not-a-number"), ("AB-2", "B", "Gadget", "", "")],
    )
    rows = read_csv(p, MASTER_REQUIRED)
    assert [r.values["part_number"] for r in rows] == ["AB-1", "AB-2"]
    assert rows[0].values["unit_cost"] == "not-a-number"


def test_make_data_writes_three_readable_files(tmp_path):
    d = make_data(
        tmp_path,
        bom_rows=[("AS-1", "FA-9", 2)],
        master_rows=[("FA-9", "B", "Screw", "Fastener", "0.10")],
        service_rows=[("FA-9", "Y", "", "")],
    )
    assert read_csv(d / "bom.csv", BOM_REQUIRED)[0].values["quantity"] == "2"
    assert read_csv(d / "parts_master.csv", MASTER_REQUIRED)[0].values["revision"] == "B"
    svc = read_csv(d / "service_parts.csv", ("part_number", "field_replaceable", "serial_from", "serial_to"))
    assert svc[0].values["field_replaceable"] == "Y"


# ---------------------------------------------------------------------------
# 12.3 Validation and conflicts
# ---------------------------------------------------------------------------


def _load(tmp_path, bom=(), master=(), service=()):
    return load_all(make_data(tmp_path, bom, master, service))


def test_invalid_bom_rows_skipped(tmp_path):
    edges, _, _ = _load(tmp_path, bom=[
        ("", "B", 1),            # blank parent
        ("A", " ", 1),           # blank child
        ("A", "a", 1),           # parent == child after norm_pn
        ("A", "C", 0),           # zero
        ("A", "D", -2),          # negative
        ("A", "E", "2.5"),       # not whole
        ("A", "F", ""),          # blank
        ("A", "G", "abc"),       # garbage
        ("A", "H", "3.0"),       # valid
        ("A", "I", "1,000"),     # valid
    ])
    assert edges == {"A": {"H": 3, "I": 1000}}


def test_validate_before_dedup(tmp_path):
    edges, _, _ = _load(tmp_path, bom=[("A", "B", "abc"), ("A", "B", 4)])
    assert edges == {"A": {"B": 4}}


@pytest.mark.parametrize(
    "qtys, expected",
    [
        ([2, 3, 3], 3),          # most common
        ([2, 3], 2),             # tie -> first
        ([4, 4, 4], 4),          # all the same
        ([5, 2, 3, 3, 2], 2),    # tie between 2 and 3 -> the tied value seen first
    ],
)
def test_conflicting_quantities(tmp_path, qtys, expected):
    edges, _, _ = _load(tmp_path, bom=[("A", "B", q) for q in qtys])
    assert edges == {"A": {"B": expected}}


def test_bom_part_numbers_normalised(tmp_path):
    edges, _, _ = _load(tmp_path, bom=[(" as-1 ", "fa\N{EN DASH}9", 2), ("AS-1", "FA-9", 2)])
    assert edges == {"AS-1": {"FA-9": 2}}


@pytest.mark.parametrize(
    "revs, expected",
    [
        (["A", "B"], "B"),
        (["B", "AA"], "AA"),
        (["", "A"], "A"),
        (["b", "a"], "B"),       # normalised to upper case
    ],
)
def test_revision_selection(tmp_path, revs, expected):
    master = [("P-1", r, f"desc {i}") for i, r in enumerate(revs)]
    _, m, _ = _load(tmp_path, bom=[("R", "P-1", 1)], master=master)
    assert m["P-1"]["revision"] == expected


def test_revision_tie_keeps_first_row(tmp_path):
    _, m, _ = _load(tmp_path, bom=[("R", "P-1", 1)], master=[("P-1", "B", "first"), ("P-1", "B", "second")])
    assert m["P-1"] == {"revision": "B", "description": "first"}


def test_master_blank_pn_skipped_and_blank_fields_kept(tmp_path):
    _, m, _ = _load(tmp_path, bom=[("R", "P-1", 1)], master=[("", "A", "no pn"), ("P-1", "", "  ")])
    assert m == {"P-1": {"revision": "", "description": ""}}


@pytest.mark.parametrize(
    "serial_from, serial_to, unrestricted, ranges",
    [
        ("", "", True, []),                      # blank / blank -> unrestricted
        ("1000", "", False, [(1000, None)]),     # open upper bound
        ("", "2000", False, [(None, 2000)]),     # open lower bound
        ("1000", "2000", False, [(1000, 2000)]),
        ("1500", "1500", False, [(1500, 1500)]),
        ("1000.0", "2,000", False, [(1000, 2000)]),
        ("2000", "1000", False, []),             # reversed -> invalid
        ("abc", "", False, []),                  # invalid on one side
        ("", "1e3", False, []),
    ],
)
def test_service_range_table(tmp_path, serial_from, serial_to, unrestricted, ranges):
    _, _, s = _load(tmp_path, service=[("P-1", "Y", serial_from, serial_to)])
    assert s["P-1"] == ServiceDecision(replaceable=True, unrestricted=unrestricted, ranges=ranges)


def test_service_decisions(tmp_path):
    _, _, s = _load(tmp_path, service=[
        ("ONLY-N", "N", "", ""),
        ("UNKNOWN", "TBD", "", ""),
        ("MIXED", "Y", "", ""),
        ("MIXED", "N", "", ""),
        ("MIXED-UNKNOWN", "Yes", "", ""),
        ("MIXED-UNKNOWN", "?", "", ""),
        ("MULTI-Y", "Y", "100", "200"),
        ("MULTI-Y", "true", "", ""),
        ("MULTI-Y", "1", "500", ""),
        ("ALL-INVALID", "Y", "9", "1"),
        ("ALL-INVALID", "Y", "x", ""),
    ])
    assert "NOROWS" not in s
    assert s["ONLY-N"] == ServiceDecision()
    assert s["UNKNOWN"] == ServiceDecision()
    assert s["MIXED"] == ServiceDecision()                   # N wins
    assert s["MIXED-UNKNOWN"] == ServiceDecision()           # unknown counts as N
    assert s["MULTI-Y"] == ServiceDecision(True, True, [(100, 200), (500, None)])
    assert s["ALL-INVALID"] == ServiceDecision(True, False, [])   # ready, but fits no serial


def test_master_alias_resolved_to_bom_spelling(tmp_path):
    _, m, s = _load(
        tmp_path,
        bom=[("AS-40000", "AS-40003", 1)],
        master=[("AS40003", "A", "Frame")],
        service=[("AS_40003", "Y", "", "")],
    )
    assert m == {"AS-40003": {"revision": "A", "description": "Frame"}}
    assert s == {"AS-40003": ServiceDecision(True, True, [])}


def test_alias_not_merged_when_two_bom_spellings_share_loose_key(tmp_path):
    _, m, _ = _load(
        tmp_path,
        bom=[("R", "GF-1", 1), ("R", "GF#1", 1)],
        master=[("GF1", "A", "ambiguous")],
    )
    assert m == {"GF1": {"revision": "A", "description": "ambiguous"}}


def test_exact_master_entry_beats_alias(tmp_path):
    _, m, _ = _load(
        tmp_path,
        bom=[("R", "AS-3", 1)],
        master=[("AS3", "Z", "alias"), ("AS-3", "A", "exact")],
    )
    assert m == {"AS-3": {"revision": "A", "description": "exact"}}


def test_two_master_aliases_merged_and_revision_reselected(tmp_path):
    _, m, _ = _load(
        tmp_path,
        bom=[("R", "AS-3", 1)],
        master=[("AS3", "A", "older"), ("AS_3", "B", "newer"), ("AS/3", "B", "newer, later row")],
    )
    assert m == {"AS-3": {"revision": "B", "description": "newer"}}


def test_service_alias_rows_merged_with_exact_rows(tmp_path):
    _, _, s = _load(
        tmp_path,
        bom=[("R", "AS-3", 1)],
        service=[("AS-3", "Y", "", ""), ("AS3", "N", "", "")],
    )
    assert s == {"AS-3": ServiceDecision()}                  # merged, N wins


def test_repeated_header_row_fails_validation(tmp_path):
    d = make_data(tmp_path, bom_rows=[("A", "B", 1)])
    with open(d / "bom.csv", "a", encoding="utf-8") as f:
        f.write("parent_pn,child_pn,quantity\nA,C,2\n")
    edges, _, _ = load_all(d)
    assert edges == {"A": {"B": 1, "C": 2}}


def test_load_all_on_visible_data_does_not_crash():
    from app.config import DATA_DIR
    edges, master, service = load_all(DATA_DIR)
    assert edges and master and service
