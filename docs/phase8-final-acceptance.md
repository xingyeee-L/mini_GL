# Phase 8 final acceptance

## Shipped scope

- Agent-executable actions are limited to local search, grounded answer, and source preview.
- Every executable request is re-authorized on the server through the intersection of user,
  agent, tool, and policy permissions.
- Retrieved content and client request fields are never treated as authorization.
- Audit evidence contains action metadata only; prompts and document content are excluded.
- Write-like and destructive actions remain outside the Agent executor.

## Security review resolution

The independent review found risks around caller-supplied confirmation, forgeable decisions,
audit-state deduplication, exact expiry handling, and interrupted simulation recovery. Phase 8
closes these with signed decisions, fixed action-to-risk validation, server-minted permissions,
append-safe event identities, one-time confirmation cleanup, database constraints, and
fail-closed startup recovery.

## Acceptance evidence

- 74 automated unit and integration tests pass.
- Ruff, strict mypy, compileall, and Git whitespace checks pass.
- Browser verification confirms the redesigned page renders at desktop width without horizontal
  overflow, exposes the Agent safety controls, and performs a real indexed search.
- The visual console remains loopback-only and reports local model and privacy status.

## Deliberate non-goals

Phase 8 does not expose arbitrary shell, arbitrary path, arbitrary network, source revocation,
derived-data deletion, index rebuild, or pause/resume through an Agent executor. Any future write
executor requires a new threat review and dedicated side-effect/rollback acceptance tests.
