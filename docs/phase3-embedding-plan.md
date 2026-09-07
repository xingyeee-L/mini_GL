# Phase 3 Embedding and Hybrid Retrieval Plan

## Architecture now available

Phase 3 starts with a typed `EmbeddingProvider`, persistent local vector records, cosine search,
reciprocal-rank fusion, and a replaceable reranker. The built-in deterministic projection verifies
indexing, caching, filtering, restart behavior, and fusion without network access. It is explicitly
not a semantic model and must not be used to claim semantic quality.

## Candidate models for the local benchmark

1. `BAAI/bge-small-zh-v1.5` — compact Chinese retrieval baseline.
2. `intfloat/multilingual-e5-small` — multilingual baseline with documented query/passage prefixes.
3. `jinaai/jina-embeddings-v3` — broader multilingual candidate, evaluated only if the machine can
   run it comfortably and its model code/dependency requirements pass review.

Model weights must be downloaded only after explicit review of size, license, dependencies, and
hardware fit. Runtime must support a strict offline mode and must never silently call a hosted API.

## Fair comparison

- Keep the 15-document, 25-query Chinese fixture frozen.
- Compare lexical-only, vector-only, hybrid, and hybrid-plus-reranker.
- Record Recall@5, Recall@10, MRR, forbidden-result rate, P50/P95 latency, peak memory, index size,
  and cold-start time.
- Apply the identical source scope before scoring any vector candidate.
- Select a model only if hybrid retrieval improves semantic-target queries while forbidden results
  remain zero.
