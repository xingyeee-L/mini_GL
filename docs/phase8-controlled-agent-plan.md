# Phase 8: Controlled Agent Capabilities

## Safety gate

The first slice contains authorization decisions and audit metadata only. It exposes no executor,
shell, arbitrary path, network, or source-file write capability. Independent agent security review
remains a prerequisite before any action executor is connected.

## Authorization model

An action is eligible only when it appears in the intersection of User, Agent, Tool, and Policy
permissions. Missing authority fails closed. Read-only search, answer, and source display are the
lowest-risk actions. Rebuilding derived indexes and pausing/resuming a source are reversible but
require a UUID idempotency key. Deleting derived data and revoking a source additionally require an
explicit human-confirmation decision.

Retrieved text is not a policy input and cannot grant permissions. The action enum contains no
shell, arbitrary filesystem, or network operation.

## Audit boundary

Each decision has a deterministic event ID derived from idempotency key, action, and source ID.
SQLite stores only those identifiers, decision, risk, reason code, and timestamp. Repeated requests
are deduplicated. Prompts, queries, document/chat content, credentials, and model output are not
accepted by the audit API or represented in its schema.

## Metadata-only workflow slice

Write-like decisions can now enter a workflow ledger, but no real executor is connected. The only
legal transitions are confirmation-required → ready → simulating → succeeded/failed, and failed →
compensated. Invalid state jumps fail closed. Confirmation tickets are random, stored only as a
SHA-256 digest, bound to one idempotent workflow, expire within at most 15 minutes, and cannot be
replayed after confirmation. Failure and compensation details are restricted to short status codes
so content cannot leak into the ledger.
