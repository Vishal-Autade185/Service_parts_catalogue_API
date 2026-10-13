"""Pydantic API response models (PRODUCT.md section 10).

Types only, no numeric constraints: a data quirk must never become a 500.
Descriptions and examples are documentation only (/docs); examples are real values from data/.
Field order is the JSON field order."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PartChild(BaseModel):
    part_number: str = Field(examples=["FA-30022"])
    quantity: int = Field(description="Number per parent.", examples=[3])


class PartInfoResponse(BaseModel):
    part_number: str = Field(description="Canonical (BOM) spelling.", examples=["AS-40209"])
    description: str | None = Field(description="From the latest revision; null if `missing`.",
                                    examples=["Infeed conveyor sub-assembly 2.5 insert holder"])
    revision: str | None = Field(description="Latest revision; null if `missing`.", examples=["A"])
    status: Literal["ready", "missing", "not_replaceable"] = Field(
        description="`ready`: in parts master and marked Y. `not_replaceable`: in parts master, not marked Y. "
                    "`missing`: not in parts master.",
        examples=["not_replaceable"],
    )
    total_quantity: int = Field(description="Number in one complete machine.", examples=[1])
    parents: list[str] = Field(description="Assemblies that directly contain this part.", examples=[["AS-40208"]])
    children: list[PartChild] = Field(
        description="Direct children.",
        examples=[[{"part_number": "EL-10335", "quantity": 1}, {"part_number": "FA-30022", "quantity": 3}]],
    )


class PathsResponse(BaseModel):
    part_number: str = Field(description="Canonical (BOM) spelling.", examples=["AS-40209"])
    paths: list[list[str]] = Field(description="Every path from the root to the part, sorted.",
                                   examples=[[["AS-40000", "AS-40001", "AS-40002", "AS-40208", "AS-40209"]]])


class ValidationCounts(BaseModel):
    parts: int = Field(description="Parts in the machine.", examples=[875])
    ready: int = Field(examples=[483])
    missing: int = Field(examples=[25])
    not_replaceable: int = Field(examples=[367])


class SerialApplicableResponse(BaseModel):
    serial: int = Field(examples=[2500])
    applicable_parts: int = Field(description="Ready parts that fit this serial.", examples=[448])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ErrorResponse(BaseModel):
    detail: str
