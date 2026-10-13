"""Shared test helpers (PRODUCT.md section 12)."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

BOM_HEADER = ("parent_pn", "child_pn", "quantity")
MASTER_HEADER = ("part_number", "revision", "description", "category", "unit_cost")
SERVICE_HEADER = ("part_number", "field_replaceable", "serial_from", "serial_to")


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def make_data(tmp_path: Path, bom_rows=(), master_rows=(), service_rows=()) -> Path:
    """Write bom.csv, parts_master.csv and service_parts.csv into tmp_path and return it.

    Each row is a tuple in header order; master rows may omit category/unit_cost."""
    write_csv(tmp_path / "bom.csv", BOM_HEADER, bom_rows)
    write_csv(tmp_path / "parts_master.csv", MASTER_HEADER, master_rows)
    write_csv(tmp_path / "service_parts.csv", SERVICE_HEADER, service_rows)
    return tmp_path


def build(data_dir: Path, root: str):
    """Build the catalogue from a data directory."""
    from app.catalogue import build_catalogue
    return build_catalogue(data_dir, root)
