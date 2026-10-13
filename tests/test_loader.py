from __future__ import annotations

import pytest

from app.loader import BLANK, INVALID, norm_pn, parse_flag, parse_int, rev_key

# ---------------------------------------------------------------------------
# 12.1 Value helpers
# ---------------------------------------------------------------------------


def test_norm_pn_spec_assertions():
    assert norm_pn("GF​48488") == "GF48488"          # zero-width space
    assert norm_pn("GF 48488") == "GF48488"          # non-breaking space
    assert norm_pn(" fa-30013 ") == "FA-30013"
    assert norm_pn("ＡＳ-40000") == "AS-40000"    # full-width "AS"
    assert norm_pn("AS–40000") == "AS-40000"         # en dash
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
