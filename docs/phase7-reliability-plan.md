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

## Initial synthetic baseline (2026-09-08)

On the current Windows development laptop, a generated directory containing 1,000 files of 4 KiB
each completed registration, ingestion, normalization, SQLite persistence, and lexical indexing
in 4,023 ms wall time and 3,438 ms CPU time. It produced 1,000 documents and 4,000 lexical chunks,
with a 14.773 MiB database and a 16.633 MiB peak of Python-tracked allocations. The aggregate
source digest was identical before and after the run. These numbers are an initial local baseline,
not a cross-machine performance guarantee.

A separate boundary run processed one 10 MiB synthetic text file in 4,231 ms wall time and
3,625 ms CPU time. It produced 9,571 lexical chunks, used 51.083 MiB of Python-tracked peak
allocations, and created a 31.527 MiB database. Its source digest also remained unchanged. The
generator rejects configurations above 5,000 files, 10 MiB per file, or 64 MiB total.

## Remaining phase work

- Establish large-file and large-directory ingestion limits and latency/resource baselines. A
  bounded `benchmark-ingestion` command now generates 1–5,000 synthetic files of at most 10 MiB
  each and at most 64 MiB in total. It reports wall/CPU time, Python allocation peak, database
  size, and source preservation.
- Add explicit resumable synchronization behavior beyond interrupted-run rollback.
- Exercise source revocation and complete derived-data cleanup. `revoke` now requires the final
  eight source-ID characters, deletes the registration through foreign-key cascades, and verifies
  that original files remain byte-for-byte unchanged.
- Record CPU, memory, GPU, and disk baselines for ingestion, retrieval, and generation.
- Lock dependencies and perform a supply-chain review.
- Audit every log and error path for content, query, credential, and endpoint leakage.
- Add deterministic fault injection and a bounded long-running soak test.
