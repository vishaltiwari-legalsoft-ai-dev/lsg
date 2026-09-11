"""GET /api/health -- a real round-trip to Postgres, not just "the process
is alive". Deliberately does NOT use the shared `ConnDep` pool dependency:
that dependency raising IS the down case, and this route needs to catch it
and answer gracefully rather than surface a 500."""

from __future__ import annotations

from fastapi import APIRouter

from lge.api.deps import get_pool
from lge.api.models import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])

API_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        with get_pool().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_status = "ok"
    except Exception:
        db_status = "down"
    return HealthResponse(db=db_status, version=API_VERSION)
