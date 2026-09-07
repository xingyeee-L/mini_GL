# Phase 5 Privacy and Path Review

Date: 2026-09-08

## Reviewed boundary

The review covers neutral chat JSON parsing, synthetic QQ/WeChat conversion, SQLite import,
indexing, citation reveal, CLI entry points, and the loopback acceptance page. Only fictional
fixtures were used. No real chat export or file under `data/` was opened for review.

## Controls verified

- Import requires an explicit authorization confirmation in both CLI and browser UI.
- Inputs are canonicalized under their selected parent, limited to `.json` and 10 MiB, and reject
  symbolic links and Windows reparse points.
- Reads compare device, file identity, size, and nanosecond modification time before and after;
  a changing input fails closed before database mutation.
- JSON must be strict UTF-8 and schema version `1.0`; message IDs, timezone-aware timestamps,
  message types, reply references, and bounded field sizes are validated.
- Withdrawn text is discarded. Attachment references are inert strings and are not opened.
- Conversion output must be a new `.json` file inside an existing, non-link directory and uses
  exclusive creation, so it cannot overwrite an existing file.
- Import uses the existing atomic run/event pipeline. Failures roll back; repeated imports are
  idempotent; deletion affects only derived database/index records.
- Citation reveal accepts only the exact registered export file and rechecks link/reparse status.
- The local web API remains loopback-only, CSRF-protected, size-bounded, and free of body logging.

## Explicit exclusions

The project does not decrypt client databases, inject into QQ/WeChat, automate login, scrape a
running client, resolve attachment paths, or upload content. The synthetic adapters are test
contracts, not compatibility claims for proprietary or changing real-world export formats.

## Residual risks before real data

- A user must independently obtain an export they are legally permitted to process.
- Real export format documentation and representative redacted samples are still required before
  building a production adapter.
- Multi-conversation packages, very large histories, attachment ingestion, contact alias merging,
  and OS-level access-control changes are outside phase 5.
- Before the first real import, repeat this review against the exact exporter and a minimal
  redacted sample, then confirm the source and derived-data retention policy with the user.

## Decision

Phase 5 synthetic acceptance is approved. Real-data ingestion remains gated on a separate,
exporter-specific review and explicit user authorization.
