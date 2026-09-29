"""The FastAPI app: CORS, routers, and the one error shape every response
uses (plan/api-contract.md: `{"error": {"code","message","fix"}}`). Bound
to 127.0.0.1:8100 by `lge serve` / `scripts/export_openapi.py`'s uvicorn
invocation -- this module itself is transport-agnostic.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from lge import auth as auth_store
from lge.api.deps import close_pool, get_pool
from lge.api.gate import require_access
from lge.api.routes import (
    actions,
    auth,
    firms,
    handcheck,
    health,
    imports,
    journey,
    leads,
    meta,
    overview,
    pipeline,
    qualified,
    today,
    users,
)

logger = logging.getLogger("lge.api")
# The engine's own HTTP calls (verifiers, search) must never print a URL
# that carries a key or a person's address into the API log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Only our own screens. They reach the engine through their own server's
# /api proxy, so they never need this; it is for a page calling the engine
# directly. Port 3000 belongs to another project on this machine, and a page
# there must not be able to read contacts, which are personal data.
_ALLOWED_ORIGINS = ["http://localhost:5000", "http://127.0.0.1:5000"]

_HTTP_STATUS_CODE: dict[int, str] = {
    400: "bad_request",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    pool = get_pool()  # open the pool eagerly, not on the first request
    # A job left queued or running belonged to the process that just died:
    # fail it, so the screen stops waiting and the firm can be asked again.
    with pool.connection() as conn:
        swept = actions.sweep_orphaned_jobs(conn)
        stuck = imports.sweep_orphaned_imports(conn)
        auth_store.sweep_sessions(conn)
    if swept:
        logger.warning("failed %d job(s) orphaned by the last restart", swept)
    if stuck:
        logger.warning("failed %d import(s) left loading by the last restart", stuck)
    yield
    close_pool()


app = FastAPI(title="Lead Gen Engine API", lifespan=_lifespan)

# Binding to 127.0.0.1 keeps other machines out; a Host check keeps out a
# page elsewhere that re-points its own name at 127.0.0.1 (DNS rebinding)
# and would otherwise read contacts or start paid research from the LAN.
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health and sign-in stand outside the door; the Users screen has its own
# (admin-only) gate; every other route is behind `require_access` (D-067),
# which is open until Google sign-in is configured.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
_gate = [Depends(require_access)]
for _router in (
    today.router, leads.router, firms.router, handcheck.router, meta.router,
    pipeline.router, imports.router, actions.router, overview.router, qualified.router,
    journey.router,
):
    app.include_router(_router, dependencies=_gate)


def _error_body(code: str, message: str, fix: str | None = None) -> dict:
    body: dict[str, str] = {"code": code, "message": message}
    if fix:
        body["fix"] = fix
    return {"error": body}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        body = _error_body(detail["code"], detail["message"], detail.get("fix"))
    else:
        code = _HTTP_STATUS_CODE.get(exc.status_code, "error")
        body = _error_body(code, str(detail))
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    message = f"{loc}: {first.get('msg')}" if loc else "The request did not match the contract."
    return JSONResponse(status_code=422, content=_error_body("validation_error", message))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full context/stack to the logs; the client gets a stable, safe shape --
    # never the exception text itself (senior-backend "Error taxonomy" rule).
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_body(
            "internal_error", "Something went wrong on our side.", "Try again in a moment."
        ),
    )
