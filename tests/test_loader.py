from __future__ import annotations

import pytest

from app.loader import (
    BLANK,
    INVALID,
    StartupError,
    canon_header,
    norm_pn,
    parse_flag,
    parse_int,
    read_csv,
    rev_key,
)
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
