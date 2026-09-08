# ADR 0004: Bounded Recovery and Reliability Operations

## Status

Accepted on 2026-09-08.

## Decision

mini_GL uses SQLite's online backup API for consistent snapshots and permits restoration only to a
new path. Every snapshot and restored database must pass `PRAGMA quick_check`; commands return a
SHA-256 receipt. Source revocation requires a source-ID suffix confirmation and deletes only
application-owned state through database cascades.

Interrupted synchronization restarts from the last committed snapshot instead of attempting to
continue from partially parsed content. The approach repeats safe read-only work, but avoids
publishing incomplete document or deletion state. Fault injection occurs after scanning and before
the atomic commit to preserve this invariant.

Performance and soak tools generate bounded synthetic data internally. They never accept or scan
a user source path. Development and optional ML dependencies are captured as exact-version lock
files, while the core runtime retains no PyPI dependency.

## Consequences

- Recovery is simple, inspectable, and cannot overwrite an existing database.
- A resumed scan may repeat parsing work, but state remains correct and idempotent.
- Benchmark figures describe this development laptop rather than a universal capacity guarantee.
- Exact pins improve repeatability, but artifact hashes and signed provenance remain future
  supply-chain hardening work.
