"""FastAPI app: lifespan, routes and the test page (PRODUCT.md section 9)."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.catalogue import Catalogue, build_catalogue
from app.loader import loose_key, norm_pn
from models import (
    ErrorResponse,
    HealthResponse,
    PartInfoResponse,
    PathsResponse,
    SerialApplicableResponse,
    ValidationCounts,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

log = logging.getLogger("app")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    log.addHandler(_handler)
_level = logging.getLevelName(config.LOG_LEVEL.upper())
log.setLevel(_level if isinstance(_level, int) else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uvicorn accepts no connections until this has finished.
    app.state.catalogue = build_catalogue(config.DATA_DIR, config.ROOT_PN)
    yield


def error(description: str, example: str) -> dict:
    """OpenAPI entry for an error response, with its real message as the example."""
    return {"model": ErrorResponse, "description": description,
            "content": {"application/json": {"example": {"detail": example}}}}


app = FastAPI(
    title="Service Parts Catalogue API",
    version="1.0.0",
    description="Parts catalogue for the AM-700 machine (root `AS-40000`). "
                "Part numbers match regardless of case, spaces or dash style.",
    lifespan=lifespan,
    responses={500: error("Internal error", "Internal error")},
)

NOT_FOUND = {404: error("Part not in the machine", "Part 'XX-1' is not in the machine")}

PartNumber = Annotated[
    str,
    PathParam(description="Encode `#` as `%23` and `/` as `%2F`.", examples=["AS-40209"]),
]

_default_openapi = app.openapi


def openapi_without_422() -> dict:
    """FastAPI lists a 422 for every endpoint with a parameter, but plain `str` path parameters
    never fail validation here (unknown parts are 404, bad serials 400), so drop it from the docs."""
    if app.openapi_schema is None:
        schema = _default_openapi()
        for operations in schema["paths"].values():
            for operation in operations.values():
                operation["responses"].pop("422", None)
        for name in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(name, None)
    return app.openapi_schema


app.openapi = openapi_without_422


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal error"})


def catalogue(request: Request) -> Catalogue:
    return request.app.state.catalogue


def resolve_part(cat: Catalogue, raw: str) -> str | None:
    """(9.4) Exact canonical match, else a unique loose-key match."""
    pn = norm_pn(raw)
    if not pn:
        return None
    if pn in cat.part_info:
        return pn
    matches = cat.machine_loose.get(loose_key(pn), [])
    return matches[0] if len(matches) == 1 else None


def part_or_404(request: Request, raw: str) -> str:
    pn = resolve_part(catalogue(request), raw)
    if pn is None:
        raise HTTPException(404, f"Part '{raw}' is not in the machine")
    return pn


@app.get("/health", response_model=HealthResponse, tags=["System"], summary="Health check")
def health():
    return {"status": "ok"}


@app.get("/api/validation", response_model=ValidationCounts, tags=["Catalogue"], summary="Part counts by status")
def validation(request: Request):
    return catalogue(request).counts


# The paths route must be declared first: {part_number:path} would otherwise swallow "/paths".
@app.get("/api/parts/{part_number:path}/paths", response_model=PathsResponse, responses=NOT_FOUND,
         tags=["Parts"], summary="Paths from the root to a part")
def part_paths(part_number: PartNumber, request: Request):
    pn = part_or_404(request, part_number)
    return {"part_number": pn, "paths": catalogue(request).paths(pn)}


@app.get("/api/parts/{part_number:path}", response_model=PartInfoResponse, responses=NOT_FOUND,
         tags=["Parts"], summary="Part details")
def part_info(part_number: PartNumber, request: Request):
    return catalogue(request).part_info[part_or_404(request, part_number)]


@app.get(
    "/api/serial/{serial}",
    response_model=SerialApplicableResponse,
    responses={400: error("Not a whole number, or too long", "Serial '2500.5' is not a whole number")},
    tags=["Serials"],
    summary="Ready parts that fit a serial",
    description="Ready parts whose serial range includes the serial (ends included), plus ready parts with no range.",
)
def serial_applicable(
    serial: Annotated[str, PathParam(description="Whole number.", examples=["2500"])],
    request: Request,
):
    s = serial.strip()
    if not re.fullmatch(r"[+-]?[0-9]+", s):
        raise HTTPException(400, f"Serial '{serial}' is not a whole number")
    try:
        n = int(s)
    except ValueError:                       # Python's 4300-digit int() limit
        raise HTTPException(400, "Serial number is too long")
    return {"serial": n, "applicable_parts": catalogue(request).applicable(n)}


@app.get("/", include_in_schema=False)
def page():
    return FileResponse(STATIC_DIR / "index.html")
