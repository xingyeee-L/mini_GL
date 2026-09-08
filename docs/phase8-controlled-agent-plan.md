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
