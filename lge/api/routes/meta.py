"""GET /api/meta/providers -- booleans only, never key values."""

from __future__ import annotations

from fastapi import APIRouter

from lge.api.deps import providers_status
from lge.api.models import ProvidersResponse

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/providers", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    return ProvidersResponse(**providers_status())
