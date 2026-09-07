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

- Keep each published fixture version frozen; use the 30-document, 60-query version-two fixture for
  current comparisons while retaining all version-one cases as regression anchors.
- Compare lexical-only, vector-only, hybrid, and hybrid-plus-reranker.
- Record Recall@5, Recall@10, MRR, forbidden-result rate, P50/P95 latency, peak memory, index size,
  and cold-start time.
- Apply the identical source scope before scoring any vector candidate.
- Select a model only if hybrid retrieval improves semantic-target queries while forbidden results
  remain zero.

## First real-model result

Hardware: Ryzen 9 6900HX, 15.3 GB RAM, RTX 3060 Laptop 6 GB. The installed PyTorch build runs on
CPU, which is sufficient for the first 24M-parameter baseline. `BAAI/bge-small-zh-v1.5` is pinned
to revision `a7ec18349c42fc774b0e86af26215e38a10fbe9d` and loaded from the ignored local `models/`
directory with network access disabled at runtime.

Frozen 15-document/25-query benchmark:

| Route | Recall@5 | Recall@10 | MRR | Forbidden | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.66 | 0.66 | 0.56 | 0.0 | 0.39 ms | 0.49 ms |
| BGE vector | 0.94 | 0.98 | 0.7297 | 0.0 | 12.34 ms | 13.89 ms |
| BGE + BM25 + reranker | 0.92 | 0.98 | 0.7590 | 0.0 | 12.80 ms | 13.97 ms |

Indexing 15 documents took approximately 238 ms on CPU. Hybrid retrieval provides the best MRR;
vector-only has slightly better Recall@5. The next iteration should tune fusion using a larger
fixture rather than optimizing these 25 queries directly.

## Expanded benchmark result

The version-two benchmark contains 30 documents and 60 queries, including paraphrases, hard
negatives, overlapping targets, permissions, local-only operation, prompt injection, and index
lifecycle questions.

| Route | Recall@5 | Recall@10 | MRR | Forbidden | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.6750 | 0.6750 | 0.6589 | 0.0 | 0.83 ms | 1.03 ms |
| BGE vector | 0.9083 | 0.9583 | 0.7868 | 0.0 | 12.06 ms | 13.40 ms |
| BGE hybrid | 0.9417 | 0.9917 | 0.7994 | 0.0 | 14.42 ms | 15.86 ms |
| E5 vector | 0.9333 | 1.0000 | 0.8189 | 0.0 | 20.81 ms | 23.58 ms |
| E5 hybrid | 0.9250 | 1.0000 | 0.7957 | 0.0 | 22.33 ms | 25.15 ms |

BGE loaded cold in approximately 10.4 seconds, indexed 30 vectors in 255 ms, used 60 KiB of vector
storage, and reached a process peak working set of 578 MiB. E5 loaded in approximately 12.3 seconds,
indexed in 442 ms, used 45 KiB, and reached 894 MiB. E5 vector-only has the highest absolute quality,
but BGE is materially faster and lighter, and the chosen BGE hybrid route exceeds both BM25 and BGE
vector-only on Recall@5, Recall@10, and MRR while keeping forbidden results at zero.

## Phase-three decision

- Default provider: pinned `BAAI/bge-small-zh-v1.5`, strictly offline on CPU.
- Comparison provider: pinned `intfloat/multilingual-e5-small` with required `query:` and `passage:`
  prefixes. It remains available when higher vector-only quality is worth the memory and latency.
- Fusion: vector-weighted RRF plus a bounded lexical-overlap adjustment; lexical evidence cannot
  overwrite the semantic ranking by itself.
- Incremental lifecycle: stable lexical chunks retain their vectors, new or changed chunks alone
  are embedded, and deleted documents cascade only into application-owned derived indexes.
- Storage: provider is part of the vector primary key, so pinned model indexes can coexist and be
  switched without corrupting each other.

Phase three is complete for the current 30-document/60-query acceptance set. Larger-corpus stress
testing and GPU measurements belong to phase seven, rather than blocking the retrieval architecture.
