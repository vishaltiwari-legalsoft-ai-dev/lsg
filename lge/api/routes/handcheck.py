"""GET /api/handcheck, POST /api/handcheck/{firm_id}/{attr} -- gate G2.
The sample, gate math and accuracy rollup all come from
`lge.api.handcheck_logic`, shared with `GET /api/today`'s queue count.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from lge.api.deps import ConnDep
from lge.api.handcheck_logic import build_handcheck_response
from lge.api.models import HandcheckDecisionRequest, HandcheckResponse

router = APIRouter(prefix="/api/handcheck", tags=["handcheck"])


@router.get("", response_model=HandcheckResponse)
def get_handcheck(conn: ConnDep) -> HandcheckResponse:
    return HandcheckResponse(**build_handcheck_response(conn))


@router.post("/{firm_id}/{attr}", status_code=204)
def post_handcheck_decision(
    firm_id: str, attr: str, body: HandcheckDecisionRequest, conn: ConnDep
) -> Response:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO handcheck_result (firm_id, attr, correct, corrected_value, reviewer, at)
            VALUES (%s, %s, %s, %s, 'ui', now())
            ON CONFLICT (firm_id, attr) DO UPDATE
              SET correct = EXCLUDED.correct,
                  corrected_value = EXCLUDED.corrected_value,
                  reviewer = EXCLUDED.reviewer,
                  at = EXCLUDED.at
            """,
            (firm_id, attr, body.correct, body.corrected_value),
        )
    return Response(status_code=204)
