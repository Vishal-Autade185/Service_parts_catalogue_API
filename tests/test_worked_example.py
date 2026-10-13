"""PRODUCT.md 12.5: the worked example from Appendix Q of the brief, root AS-1."""
from __future__ import annotations

import pytest

from tests.conftest import build, make_data

BOM = [("AS-1", "AS-2", 2), ("AS-1", "FA-9", 4), ("AS-2", "FA-9", 3), ("AS-2", "EL-5", 1)]
MASTER = [("AS-1", "A", ""), ("AS-2", "A", ""), ("FA-9", "A", ""), ("FA-9", "B", "")]
SERVICE = [("AS-2", "Y", "", ""), ("FA-9", "Y", "", ""), ("EL-5", "Y", "1000", "1999")]


@pytest.fixture
def cat(tmp_path):
    return build(make_data(tmp_path, BOM, MASTER, SERVICE), "AS-1")


def test_validation_counts(cat):
    assert cat.counts == {"parts": 4, "ready": 2, "missing": 1, "not_replaceable": 1}


def test_statuses(cat):
    assert {pn: info["status"] for pn, info in cat.part_info.items()} == {
        "AS-1": "not_replaceable", "AS-2": "ready", "FA-9": "ready", "EL-5": "missing",
    }


def test_fa9_total_quantity(cat):
    assert cat.part_info["FA-9"]["total_quantity"] == 10


def test_fa9_revision(cat):
    assert cat.part_info["FA-9"]["revision"] == "B"


def test_fa9_paths(cat):
    assert cat.paths("FA-9") == [["AS-1", "AS-2", "FA-9"], ["AS-1", "FA-9"]]


def test_fa9_parents_and_children(cat):
    assert cat.part_info["FA-9"]["parents"] == ["AS-1", "AS-2"]
    assert cat.part_info["FA-9"]["children"] == []


def test_serial_2500(cat):
    assert cat.applicable(2500) == 2


def test_root_total_and_paths(cat):
    assert cat.part_info["AS-1"]["total_quantity"] == 1
    assert cat.paths("AS-1") == [["AS-1"]]


def test_missing_part_has_no_description_or_revision(cat):
    info = cat.part_info["EL-5"]
    assert info["description"] is None and info["revision"] is None
