"""PRODUCT.md 12.11: the API through FastAPI's TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from tests.conftest import make_data

PART_FIELDS = ["part_number", "description", "revision", "status", "total_quantity", "parents", "children"]


@pytest.fixture(scope="module")
def client():
    """App built from the visible data/ folder."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def odd_client(tmp_path, monkeypatch):
    """App built from a fixture whose part numbers contain '#' and '/'."""
    d = make_data(
        tmp_path,
        [("R", "GF#1", 2), ("R", "AB/2", 1), ("AB/2", "GF#1", 3)],
        [("R", "A", "Root"), ("GF#1", "A", "Hash part"), ("AB/2", "B", "Slash part")],
        [("GF#1", "Y", "", "")],
    )
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "ROOT_PN", "R")
    with TestClient(app) as c:
        yield c


# ---- health, validation, page --------------------------------------------------------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_validation_counts(client):          # decision 16: real-data counts via the API
    r = client.get("/api/validation")
    assert r.status_code == 200
    assert list(r.json()) == ["parts", "ready", "missing", "not_replaceable"]
    assert r.json() == {"parts": 875, "ready": 483, "missing": 25, "not_replaceable": 367}


def test_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Service Parts Catalogue" in r.text


def test_docs_list_only_real_responses(client):          # decision 25: no 422 in the docs
    schema = client.get("/openapi.json").json()
    codes = {path: sorted(ops["get"]["responses"]) for path, ops in schema["paths"].items()}
    assert codes == {
        "/health": ["200", "500"],
        "/api/validation": ["200", "500"],
        "/api/parts/{part_number}/paths": ["200", "404", "500"],
        "/api/parts/{part_number}": ["200", "404", "500"],
        "/api/serial/{serial}": ["200", "400", "500"],
    }
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert client.get("/docs").status_code == 200


# ---- parts ----------------------------------------------------------------------------


def test_part_shape_and_field_order(client):
    r = client.get("/api/parts/FA-30019")
    assert r.status_code == 200
    body = r.json()
    assert list(body) == PART_FIELDS
    assert body["total_quantity"] == 178
    assert len(body["parents"]) == 22
    for child in client.get("/api/parts/AS-40209").json()["children"]:
        assert list(child) == ["part_number", "quantity"]


def test_missing_part_has_null_fields(client):
    body = client.get("/api/parts/EL-10024").json()
    assert body["status"] == "missing"
    assert body["description"] is None and body["revision"] is None


def test_paths_shape(client):
    r = client.get("/api/parts/FA-30019/paths")
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["part_number", "paths"]
    assert body["part_number"] == "FA-30019"
    assert len(body["paths"]) == 22
    assert body["paths"] == sorted(body["paths"])
    assert all(p[0] == "AS-40000" and p[-1] == "FA-30019" for p in body["paths"])


@pytest.mark.parametrize("raw, canonical", [
    ("fa-30019", "FA-30019"),
    ("%20as-40003%20", "AS-40003"),
    ("fa30019", "FA-30019"),                 # loose match
])
def test_forgiving_lookup_returns_canonical(client, raw, canonical):
    for suffix in ("", "/paths"):
        r = client.get(f"/api/parts/{raw}{suffix}")
        assert r.status_code == 200
        assert r.json()["part_number"] == canonical


@pytest.mark.parametrize("raw", ["NOPE-1", "AS-99999", "%20", "%00", "%25", "..%2F..", "a" * 500])
def test_unknown_part_is_404_never_422(client, raw):
    for suffix in ("", "/paths"):
        r = client.get(f"/api/parts/{raw}{suffix}")
        assert r.status_code == 404
        assert list(r.json()) == ["detail"]
        assert r.json()["detail"].endswith("is not in the machine")


def test_404_detail_quotes_raw_input(client):
    assert client.get("/api/parts/nope-1").json() == {"detail": "Part 'nope-1' is not in the machine"}


def test_hash_and_slash_reach_the_handler(odd_client):
    r = odd_client.get("/api/parts/GF%231")
    assert r.status_code == 200 and r.json()["part_number"] == "GF#1"
    assert r.json()["total_quantity"] == 2 + 1 * 3
    r = odd_client.get("/api/parts/AB%2F2")
    assert r.status_code == 200 and r.json()["part_number"] == "AB/2"
    r = odd_client.get("/api/parts/AB%2F2/paths")
    assert r.json() == {"part_number": "AB/2", "paths": [["R", "AB/2"]]}
    r = odd_client.get("/api/parts/GF%231/paths")
    assert r.json()["paths"] == [["R", "AB/2", "GF#1"], ["R", "GF#1"]]
    assert odd_client.get("/api/parts/gf1").json()["part_number"] == "GF#1"     # loose match


# ---- serials ----------------------------------------------------------------------------


@pytest.mark.parametrize("raw, value", [("2500", 2500), ("0", 0), ("-5", -5), ("%2B7", 7), ("007", 7), ("%202500%20", 2500)])
def test_serial_accepted(client, raw, value):
    r = client.get(f"/api/serial/{raw}")
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["serial", "applicable_parts"]
    assert body["serial"] == value
    assert isinstance(body["applicable_parts"], int)


@pytest.mark.parametrize("raw", ["abc", "2500.5", "2500.0", "1e3", "%20", "12a", "%EF%BC%91"])
def test_serial_rejected(client, raw):
    r = client.get(f"/api/serial/{raw}")
    assert r.status_code == 400
    assert "not a whole number" in r.json()["detail"]


def test_serial_long_numbers(client):
    assert client.get("/api/serial/" + "9" * 1000).status_code == 200
    r = client.get("/api/serial/" + "9" * 5000)
    assert r.status_code == 400
    assert r.json() == {"detail": "Serial number is too long"}


def test_serial_counts_follow_catalogue(client):
    cat = client.app.state.catalogue
    for s in (0, 1000, 2500, 10**30):
        assert client.get(f"/api/serial/{s}").json()["applicable_parts"] == cat.applicable(s)


# ---- global exception handler (decision 19) ----------------------------------------------


def test_unhandled_error_returns_json_500(client):
    def boom():
        raise RuntimeError("forced")
    app.add_api_route("/__boom", boom)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/__boom")
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", None) != "/__boom"]
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal error"}
