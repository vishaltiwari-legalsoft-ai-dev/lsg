"""GET /api/handcheck, POST /api/handcheck/{firm_id}/{attr} -- gate G2.
The sample, gate math and accuracy rollup all come from
`lge.api.handcheck_logic`, shared with `GET /api/today`'s queue count.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from lge.api.deps import ConnDep
from lge.api.errors import api_error, is_uuid, not_found
from lge.api.gate import actor_of
from lge.api.handcheck_logic import build_handcheck_response
from lge.api.models import HandcheckDecisionRequest, HandcheckResponse

router = APIRouter(prefix="/api/handcheck", tags=["handcheck"])


@router.get("", response_model=HandcheckResponse)
def get_handcheck(conn: ConnDep) -> HandcheckResponse:
    return HandcheckResponse(**build_handcheck_response(conn))


@router.post("/{firm_id}/{attr}", status_code=204)
def post_handcheck_decision(
    firm_id: str, attr: str, body: HandcheckDecisionRequest, conn: ConnDep, request: Request
) -> Response:
    # A decision is recorded only for a firm that exists and an attribute it
    # has: before this, an unknown firm was a 500 on the foreign key and a
    # mistyped attribute a junk row that counted toward the gate.
    if not is_uuid(firm_id):
        raise not_found("Firm not found.", "Check the id.")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM firm WHERE id = %s", (firm_id,))
        if cur.fetchone() is None:
            raise not_found("Firm not found.", "Check the id.")
        # An attribute the firm has at least one claim for: what the
        # hand-check screen shows and can be judged.
        cur.execute(
            "SELECT 1 FROM firm_attribute WHERE firm_id = %s AND attr = %s LIMIT 1",
            (firm_id, attr),
        )
        known = cur.fetchone() is not None
    if not known:
        raise api_error(
            400, "bad_request", f"'{attr}' is not an attribute of this firm.",
            "Decide on one of the attributes the hand-check shows.",
        )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO handcheck_result (firm_id, attr, correct, corrected_value, reviewer, at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (firm_id, attr) DO UPDATE
              SET correct = EXCLUDED.correct,
                  corrected_value = EXCLUDED.corrected_value,
                  reviewer = EXCLUDED.reviewer,
                  at = EXCLUDED.at
            """,
            (firm_id, attr, body.correct, body.corrected_value, actor_of(request)),
        )
    return Response(status_code=204)
