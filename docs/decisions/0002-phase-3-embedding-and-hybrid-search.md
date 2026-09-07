# ADR 0002: Phase 3 embedding and hybrid retrieval

## Status

Accepted on 2026-09-07.

## Decision

Use pinned BGE-small-zh-v1.5 as the default offline embedding provider. Store vectors in SQLite
under a composite `(chunk_id, provider)` identity and update them incrementally after lexical chunk
synchronization. Retrieve with vector-weighted reciprocal-rank fusion and apply only a bounded local
token-overlap adjustment.

Keep pinned multilingual-e5-small as an optional comparison provider. Apply its documented
`query:` and `passage:` prefixes at the provider boundary so callers cannot accidentally produce an
invalid comparison.

## Evidence

On the frozen 30-document/60-query Chinese benchmark, BGE hybrid reached Recall@5 0.9417,
Recall@10 0.9917, MRR 0.7994, and zero forbidden results. E5 vector-only reached higher absolute
quality but required about 894 MiB peak working set versus 578 MiB for BGE and had materially slower
queries. BGE therefore gives the better default balance for the reference laptop.

## Consequences

- Runtime remains local-only and fails closed when model files are absent.
- Multiple provider indexes may coexist safely.
- Unchanged chunks avoid repeat embedding work.
- Model, dimension, prefixes, chunking, and provider identity are versioned inputs.
- Future model changes require the same frozen benchmark and security checks.
