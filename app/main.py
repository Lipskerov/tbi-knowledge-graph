"""
TBI Knowledge Graph — FastAPI web app (v2.0).

Thin HTTP layer over `app/db.py`. Serves a read-only REST API plus the static
two-pane frontend. Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db

ROOT       = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
LIB_DIR    = ROOT / "lib"

app = FastAPI(title="TBI Knowledge Graph", version="2.0")


# ── API ─────────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/graph")
def api_graph(
    min_papers: int = 0,
    min_edge: int = 1,
    types: str | None = None,
    clusters: str | None = None,
    disease: str | None = None,
    q: str | None = None,
):
    return db.graph(min_papers=min_papers, min_edge=min_edge, types=types,
                    clusters=clusters, disease=disease, q=q)


@app.get("/api/node/{entity_id}/papers")
def api_node_papers(
    entity_id: int,
    year_min: int | None = None,
    year_max: int | None = None,
    cluster: str | None = None,
    limit: int = 50,
):
    result = db.node_papers(entity_id, year_min=year_min, year_max=year_max,
                            cluster=cluster, limit=limit)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@app.get("/api/entity/{entity_id}")
def api_entity(entity_id: int):
    result = db.entity(entity_id)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@app.get("/api/search")
def api_search(
    q: str = Query(..., description="Free-text query over abstracts (FTS5)"),
    clusters: str | None = None,
    types: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    limit: int = 50,
):
    return db.search(q, clusters=clusters, types=types,
                     year_min=year_min, year_max=year_max, limit=limit)


# ── Static assets ───────────────────────────────────────────────────────────────
# Vendored PyVis libs (vis-9.1.2, tom-select, bindings/utils.js). Generated from
# the installed pyvis package at build time (see scripts/vendor_lib.py); mounted
# only if present so the app still boots for API-only use.
if LIB_DIR.exists():
    app.mount("/lib", StaticFiles(directory=str(LIB_DIR)), name="lib")

# Frontend (index.html, app.js, styles.css) at the web root. Mounted last so the
# API routes above take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
