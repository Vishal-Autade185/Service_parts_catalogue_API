"""PRODUCT.md 12.6: baseline on the visible data/ folder.

The /api/validation endpoint check is in test_api.py (Phase 7); here the same counts
are checked on the catalogue directly."""
from __future__ import annotations

import logging

import pytest

from app.config import DATA_DIR
from tests.conftest import build


@pytest.fixture(scope="module")
def cat():
    return build(DATA_DIR, "AS-40000")


def test_validation_counts(cat):
    assert cat.counts == {"parts": 875, "ready": 483, "missing": 25, "not_replaceable": 367}


def test_removed_cycle_edge(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        cat = build(DATA_DIR, "AS-40000")
    assert cat.removed_edges == [("AS-40209", "AS-40002", 1)]
    assert "cycle edge removed: AS-40209 -> AS-40002 x1 (back_edge)" in caplog.text


def test_as40002_parents(cat):
    assert cat.part_info["AS-40002"]["parents"] == ["AS-40001"]


def test_as40209_children(cat):
    assert cat.part_info["AS-40209"]["children"] == [
        {"part_number": "EL-10335", "quantity": 1},
        {"part_number": "FA-30022", "quantity": 3},
    ]


def test_fa30019(cat):
    info = cat.part_info["FA-30019"]
    assert info["total_quantity"] == 178
    assert len(info["parents"]) == 22
    assert len(cat.paths("FA-30019")) == 22


def test_fa30022(cat):
    info = cat.part_info["FA-30022"]
    assert info["total_quantity"] == 66
    assert len(info["parents"]) == 12
    assert "AS-40210" not in info["parents"]


def test_root(cat):
    info = cat.part_info["AS-40000"]
    assert info["status"] == "not_replaceable"
    assert info["total_quantity"] == 1


def test_missing_part(cat):
    info = cat.part_info["EL-10024"]
    assert info["status"] == "missing"
    assert info["description"] is None
    assert info["revision"] is None


def test_paths_precomputed(cat):
    assert cat.precomputed_paths is not None
    assert sum(len(cat.paths(pn)) for pn in cat.part_info) == 1242
