"""One error shape everywhere -- plan/api-contract.md:
`{"error": {"code": "not_found", "message": "...", "fix": "..."}}`. Routes
raise `api_error(...)`; `lge.api.app` installs the handler that renders it
and every FastAPI-default error the same way, so the frontend never has to
special-case a route that forgot to opt in.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException


def is_uuid(value: str) -> bool:
    """Whether a path id can be a row id at all. Every id column is a uuid;
    a truncated or pasted id fed straight into `WHERE id = %s` made Postgres
    raise and the route answer 500 where the contract promises 404
    (readiness audit, 28 Sep 2026)."""
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def api_error(status_code: int, code: str, message: str, fix: str | None = None) -> HTTPException:
    detail: dict[str, str] = {"code": code, "message": message}
    if fix:
        detail["fix"] = fix
    return HTTPException(status_code=status_code, detail=detail)


def not_found(message: str, fix: str | None = None) -> HTTPException:
    return api_error(404, "not_found", message, fix)
