"""Pydantic API response models (PRODUCT.md section 10).

Types only, no numeric constraints: a data quirk must never become a 500.
Field order is the JSON field order."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PartChild(BaseModel):
    part_number: str
    quantity: int


class PartInfoResponse(BaseModel):
    part_number: str
    description: str | None
    revision: str | None
    status: Literal["ready", "missing", "not_replaceable"]
    total_quantity: int
    parents: list[str]
    children: list[PartChild]


class PathsResponse(BaseModel):
    part_number: str
    paths: list[list[str]]


class ValidationCounts(BaseModel):
    parts: int
    ready: int
    missing: int
    not_replaceable: int


class SerialApplicableResponse(BaseModel):
    serial: int
    applicable_parts: int


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ErrorResponse(BaseModel):
    detail: str
