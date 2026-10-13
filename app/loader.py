"""Stages 1-3: read CSVs, clean values, validate rows, resolve conflicts (PRODUCT.md sections 3-6)."""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

from models import Row


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
