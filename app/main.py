"""FastAPI app: lifespan, routes and the test page (PRODUCT.md section 9)."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
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


app = FastAPI(title="Service Parts Catalogue API", lifespan=lifespan)

NOT_FOUND = {404: {"model": ErrorResponse}}


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


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@app.get("/api/validation", response_model=ValidationCounts)
def validation(request: Request):
    return catalogue(request).counts


# The paths route must be declared first: {part_number:path} would otherwise swallow "/paths".
@app.get("/api/parts/{part_number:path}/paths", response_model=PathsResponse, responses=NOT_FOUND)
def part_paths(part_number: str, request: Request):
    pn = part_or_404(request, part_number)
    return {"part_number": pn, "paths": catalogue(request).paths(pn)}


@app.get("/api/parts/{part_number:path}", response_model=PartInfoResponse, responses=NOT_FOUND)
def part_info(part_number: str, request: Request):
    return catalogue(request).part_info[part_or_404(request, part_number)]


@app.get("/api/serial/{serial}", response_model=SerialApplicableResponse,
         responses={400: {"model": ErrorResponse}})
def serial_applicable(serial: str, request: Request):
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
