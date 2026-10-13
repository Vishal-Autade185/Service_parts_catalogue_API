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


DESCRIPTION = """
Parts catalogue for the **AM-700** bottling machine by Arcadia Machines (root part `AS-40000`).

The service reconciles three CSV exports (`bom.csv`, `parts_master.csv`, `service_parts.csv`) into
one catalogue at startup and answers four questions for a field service engineer:

* **What is this part?** `GET /api/parts/{part_number}`
* **Where does it sit in the machine?** `GET /api/parts/{part_number}/paths`
* **Can it be replaced on site?** the `status` field
* **Does it fit this machine's serial number?** `GET /api/serial/{serial}`

Part numbers are matched however they are typed: case, spaces, full-width characters and dash
look-alikes are ignored, and a separator variant (`FA30019` for `FA-30019`) matches when it is
unambiguous. Responses always use the BOM spelling.

All answers are precomputed at startup, so every request is a lookup.
"""

TAGS = [
    {"name": "System", "description": "Service health."},
    {"name": "Catalogue", "description": "Whole-catalogue totals."},
    {"name": "Parts", "description": "Part details and where a part sits in the machine."},
    {"name": "Serials", "description": "Which ready parts apply to a machine serial number."},
]

app = FastAPI(
    title="Service Parts Catalogue API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
    responses={500: {"model": ErrorResponse, "description": "Unexpected internal error (should never happen)."}},
)

NOT_FOUND = {404: {"model": ErrorResponse, "description": "The part is not in the machine."}}

PartNumber = Annotated[
    str,
    PathParam(
        description="Part number, typed any way: case, spaces and dash look-alikes are ignored. "
                    "URL-encode `#` as `%23` and `/` as `%2F`.",
        examples=["FA-30019"],
    ),
]


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


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
    description="Returns `{\"status\": \"ok\"}`. The server accepts requests only after the catalogue is built, "
                "so any answer means the service is ready.",
    response_description="The service is up and the catalogue is built.",
)
def health():
    return {"status": "ok"}


@app.get(
    "/api/validation",
    response_model=ValidationCounts,
    tags=["Catalogue"],
    summary="Catalogue counts",
    description="Number of parts in the machine and how many are `ready`, `missing` and `not_replaceable`. "
                "The three status counts always add up to `parts`.",
    response_description="Part counts by status.",
)
def validation(request: Request):
    return catalogue(request).counts


# The paths route must be declared first: {part_number:path} would otherwise swallow "/paths".
@app.get(
    "/api/parts/{part_number:path}/paths",
    response_model=PathsResponse,
    responses=NOT_FOUND,
    tags=["Parts"],
    summary="Where a part sits in the machine",
    description="Every way down from the root to the part, each path listed from the root to the part. "
                "Paths are sorted part number by part number from the top, and the list is never truncated.",
    response_description="All root-to-part paths, sorted.",
)
def part_paths(part_number: PartNumber, request: Request):
    pn = part_or_404(request, part_number)
    return {"part_number": pn, "paths": catalogue(request).paths(pn)}


@app.get(
    "/api/parts/{part_number:path}",
    response_model=PartInfoResponse,
    responses=NOT_FOUND,
    tags=["Parts"],
    summary="What a part is",
    description="Description and revision (latest revision), service `status`, total quantity in one machine, "
                "and the part's direct parents and children.",
    response_description="Details of the part.",
)
def part_info(part_number: PartNumber, request: Request):
    return catalogue(request).part_info[part_or_404(request, part_number)]


@app.get(
    "/api/serial/{serial}",
    response_model=SerialApplicableResponse,
    responses={400: {"model": ErrorResponse, "description": "The serial is not a whole number, or is too long."}},
    tags=["Serials"],
    summary="Parts that fit a serial number",
    description="Counts the `ready` parts that apply to a machine with this serial number: parts whose serial "
                "range includes it (both ends included) and parts with no range. Accepts any whole number, "
                "including `0`, negatives, `+7` and leading zeros.",
    response_description="The parsed serial and the number of applicable ready parts.",
)
def serial_applicable(
    serial: Annotated[str, PathParam(description="Machine serial number (a whole number).", examples=["2500"])],
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
