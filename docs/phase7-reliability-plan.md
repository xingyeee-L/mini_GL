# Phase 7: Reliability, Performance, and Recovery

## Objective

Move mini_GL from a demonstrable local prototype toward a system that can be operated for long
periods without losing its privacy and source-preservation guarantees. Every benchmark and fault
test uses synthetic fixtures only.

## First vertical slice

- Create a consistent SQLite snapshot through the SQLite backup API while the live database can
  remain open.
- Verify every created or restored database with `PRAGMA quick_check` and return its size and
  SHA-256 digest as an auditable receipt.
- Restore only into a new database path. Existing targets, symbolic links, reparse points, missing
  parent directories, corrupt snapshots, and partial outputs are rejected.
- Normalize local-model timeout and connection failures into privacy-safe, actionable errors. The
  error never contains prompts, document text, model response bodies, or low-level endpoint data.

## CLI acceptance path

```text
python -m mini_gl backup <new-backup.sqlite3> --db <live.sqlite3>
python -m mini_gl restore <backup.sqlite3> <new-restored.sqlite3>
python -m mini_gl status --db <new-restored.sqlite3>
```

The restored status must match the source snapshot, and attempting either operation with an
existing destination must leave that destination byte-for-byte unchanged.

## Remaining phase work

- Establish large-file and large-directory ingestion limits and latency/resource baselines.
- Add explicit resumable synchronization behavior beyond interrupted-run rollback.
- Exercise source revocation and complete derived-data cleanup.
- Record CPU, memory, GPU, and disk baselines for ingestion, retrieval, and generation.
- Lock dependencies and perform a supply-chain review.
- Audit every log and error path for content, query, credential, and endpoint leakage.
- Add deterministic fault injection and a bounded long-running soak test.
