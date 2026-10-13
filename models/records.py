"""Internal record types (PRODUCT.md section 5.0). Data shapes only, no logic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Row:                     # one raw CSV line from the reader (section 3.1)
    line: int
    values: dict[str, str]
