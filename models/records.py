"""Internal record types (PRODUCT.md section 5.0). Data shapes only, no logic."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Row:                     # one raw CSV line from the reader (section 3.1)
    line: int
    values: dict[str, str]


@dataclass(frozen=True)
class BomEdge:                 # one validated bom.csv row (5.1)
    parent: str
    child: str
    qty: int
    line: int


@dataclass(frozen=True)
class MasterRow:               # one validated parts_master.csv row (5.2)
    pn: str
    rev: str
    description: str
    line: int


@dataclass(frozen=True)
class ServiceRow:              # one validated service_parts.csv row (5.3)
    pn: str
    flag: str                  # "Y" or "N"
    lo: int | None
    hi: int | None
    range_valid: bool
    line: int


@dataclass
class ServiceDecision:         # one part's resolved service status (6.3)
    replaceable: bool = False
    unrestricted: bool = False
    ranges: list[tuple[int | None, int | None]] = field(default_factory=list)
