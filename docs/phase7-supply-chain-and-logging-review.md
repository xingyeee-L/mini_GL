# Phase 7 Supply-Chain and Privacy-Logging Review

## Dependency boundary

The core application keeps an empty runtime dependency list and uses the Python standard library
for ingestion, SQLite, the loopback HTTP server, and local-model transport. Development tooling is
pinned in `requirements-dev.lock`. The optional offline embedding stack is pinned in
`requirements-ml.lock`; it is not required for keyword-only operation.

Installation may contact package indexes and model registries, but normal application operation
must work offline once packages and model weights exist. Lock files contain exact versions and no
editable, local-path, VCS, direct-URL, or untrusted extra-index entries. Future upgrades must rerun
all security and retrieval benchmarks. Cryptographic wheel hashes remain a future hardening item;
the current lock captures the environment exactly but does not prove artifact provenance.

## Privacy-safe output audit

The source tree does not configure Python logging, telemetry, crash reporting, or analytics. CLI
status reports IDs, paths, hashes, counts, timings, and error types, never document bodies. The web
server uses the default request suppression path and does not log prompts or responses. Local-model
errors are normalized without prompts, source content, response bodies, or raw low-level exception
messages. Failed synchronization errors are whitespace-normalized and capped at 500 characters.

Automated review rejects future imports of the `logging` module and verifies that `.log` files are
ignored. Existing tests separately prove that status output omits document content and that model
timeout/connection errors omit synthetic secret text. Paths remain visible where needed for local
source traceability; they should be treated as private local metadata and never uploaded.

## Residual risks

- Exact package versions do not replace signed artifacts or a hash-locked installer.
- Native ML packages have a large transitive attack surface and should be installed only from the
  official configured package index.
- Python allocation tracking does not measure every native Torch/CUDA allocation; GPU figures from
  model-specific benchmarks remain authoritative for those components.
