"""
TBI Knowledge Graph — FastAPI web app (v2.0).

Thin HTTP layer over `app/db.py`. Serves a read-only REST API plus the static
two-pane frontend, gated behind a shared-password login (see app/auth.py).
Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import auth, db

ROOT       = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
LIB_DIR    = ROOT / "lib"
LOGIN_HTML = STATIC_DIR / "login.html"

app = FastAPI(title="TBI Knowledge Graph", version="2.2")

# ── Authentication ───────────────────────────────────────────────────────────
# Paths reachable without a session (the login flow + health check). Everything
# else — the API, the frontend and the vendored libs — requires a valid session.
PUBLIC_PATHS = {"/login", "/logout", "/healthz"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or request.session.get("authed"):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "authentication required"}, status_code=401)
    return RedirectResponse(url=f"/login?next={path}", status_code=303)


# Added AFTER the gate so it wraps it: SessionMiddleware runs first and populates
# request.session before require_login reads it.
app.add_middleware(
    SessionMiddleware,
    secret_key=auth.get_session_secret(),
    session_cookie="tbi_session",
    max_age=auth.session_max_age(),
    same_site="lax",
    https_only=auth.https_only(),
)


@app.get("/healthz")
def healthz():
    return {"ok": True, "auth_configured": auth.is_configured()}


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML.read_text(encoding="utf-8")


class LoginBody(BaseModel):
    password: str
    next: str | None = "/"


@app.post("/login")
async def login_submit(body: LoginBody, request: Request):
    client = request.client.host if request.client else "anon"
    allowed, retry_after = auth.check_rate_limit(client)
    if not allowed:
        return JSONResponse(
            {"error": f"Too many attempts. Try again in {retry_after}s."},
            status_code=429,
        )
    stored = auth.get_password_hash()
    if not stored:
        return JSONResponse(
            {"error": "Login is not configured on the server yet."},
            status_code=503,
        )
    if auth.verify_password(body.password, stored):
        auth.reset_rate_limit(client)
        request.session["authed"] = True
        nxt = body.next or "/"
        if not nxt.startswith("/") or nxt.startswith("//"):  # block open redirects
            nxt = "/"
        return {"ok": True, "next": nxt}
    auth.register_failure(client)
    return JSONResponse({"error": "Incorrect password."}, status_code=401)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


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
    year_min: int | None = None,
    year_max: int | None = None,
    pathway: str | None = None,
):
    return db.graph(min_papers=min_papers, min_edge=min_edge, types=types,
                    clusters=clusters, disease=disease, q=q,
                    year_min=year_min, year_max=year_max, pathway=pathway)


@app.get("/api/node/{entity_id}/papers")
def api_node_papers(
    entity_id: int,
    year_min: int | None = None,
    year_max: int | None = None,
    cluster: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    result = db.node_papers(entity_id, year_min=year_min, year_max=year_max,
                            cluster=cluster, limit=limit, offset=offset)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@app.get("/api/edge/{a_id}/{b_id}/papers")
def api_edge_papers(
    a_id: int,
    b_id: int,
    year_min: int | None = None,
    year_max: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    result = db.edge_papers(a_id, b_id, year_min=year_min, year_max=year_max,
                            limit=limit, offset=offset)
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
