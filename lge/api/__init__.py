"""The HTTP API layer (plan/api-contract.md). One more client of the store:
every business rule is called from the engine's own functions
(`lge.export.list`, `lge.journey.build`, `lge.score.reconcile`,
`sql/002_functions.sql`, `lge.ops.alerts`) -- never re-implemented here.

`lge.api.models` is the contract itself (pydantic response models ->
`openapi.json`). `lge.api.labels` turns slugs into the plain-word strings the
contract requires the backend, never the frontend, to produce.
"""
