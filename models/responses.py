"""Pydantic API response models (PRODUCT.md section 10).

Types only, no numeric constraints: a data quirk must never become a 500.
Field descriptions and examples are documentation only (shown in /docs).
Field order is the JSON field order."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PartChild(BaseModel):
    """One direct child of an assembly."""

    part_number: str = Field(description="Canonical (BOM) part number of the child.", examples=["FA-30022"])
    quantity: int = Field(description="How many of this child one parent contains.", examples=[3])


class PartInfoResponse(BaseModel):
    """Everything known about one part in the machine."""

    part_number: str = Field(
        description="Canonical part number, always the BOM spelling, whatever spelling was requested.",
        examples=["FA-30019"],
    )
    description: str | None = Field(
        description="Description from the latest revision in the parts master; null when the part is missing.",
        examples=["Washer M4"],
    )
    revision: str | None = Field(
        description="Latest revision letter (\"\" < A < B < ... < Z < AA); null when the part is missing.",
        examples=["A"],
    )
    status: Literal["ready", "missing", "not_replaceable"] = Field(
        description=(
            "`ready`: in the parts master and marked Y (field replaceable). "
            "`not_replaceable`: in the parts master but not marked Y, or flagged both Y and N. "
            "`missing`: not in the parts master."
        ),
        examples=["ready"],
    )
    total_quantity: int = Field(
        description="How many of this part one complete machine contains, counting every assembly it appears in. "
                    "The root has 1.",
        examples=[178],
    )
    parents: list[str] = Field(
        description="Assemblies that directly contain this part, sorted. Empty for the root.",
        examples=[["AS-40001", "AS-40010"]],
    )
    children: list[PartChild] = Field(
        description="Direct children with quantities, sorted by part number. Empty for a leaf part.",
        examples=[[{"part_number": "EL-10335", "quantity": 1}, {"part_number": "FA-30022", "quantity": 3}]],
    )


class PathsResponse(BaseModel):
    """Every way down from the root to one part."""

    part_number: str = Field(description="Canonical (BOM) part number.", examples=["FA-9"])
    paths: list[list[str]] = Field(
        description="Every root-to-part path, each listed from the root to the part, sorted part number by "
                    "part number from the top. The root's only path is `[[root]]`.",
        examples=[[["AS-1", "AS-2", "FA-9"], ["AS-1", "FA-9"]]],
    )


class ValidationCounts(BaseModel):
    """Catalogue totals. `ready + missing + not_replaceable` always equals `parts`."""

    parts: int = Field(description="Number of parts in the machine (reachable from the root).", examples=[875])
    ready: int = Field(description="Parts in the parts master and marked field replaceable.", examples=[483])
    missing: int = Field(description="Parts in the machine but not in the parts master.", examples=[25])
    not_replaceable: int = Field(description="Parts in the parts master but not field replaceable.", examples=[367])


class SerialApplicableResponse(BaseModel):
    """How many ready parts apply to one machine serial number."""

    serial: int = Field(description="The serial number, parsed as a whole number.", examples=[2500])
    applicable_parts: int = Field(
        description="Ready parts whose serial range includes this serial (both ends included), plus ready parts "
                    "with no range. Each part counts once.",
        examples=[448],
    )


class HealthResponse(BaseModel):
    """Liveness check."""

    status: Literal["ok"] = Field(description="Always `ok` once the catalogue is built.", examples=["ok"])


class ErrorResponse(BaseModel):
    """Error body for 400, 404 and 500 responses."""

    detail: str = Field(description="Human-readable reason.", examples=["Part 'XX-1' is not in the machine"])
