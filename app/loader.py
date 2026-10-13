"""Stages 1-3: read CSVs, clean values, validate rows, resolve conflicts (PRODUCT.md sections 3-6)."""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Block 1: value helpers (PRODUCT.md section 4)
# ---------------------------------------------------------------------------

# Dash look-alikes -> "-": hyphen, non-breaking hyphen, figure dash, en dash, em dash,
# horizontal bar, minus sign, small em dash, small hyphen-minus, full-width hyphen-minus.
DASHES = dict.fromkeys(
    map(ord, "‐‑‒–—―−﹘﹣－"), "-"
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
