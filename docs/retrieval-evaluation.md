# Retrieval and RAG Evaluation

## Why evaluation starts before the LLM

If the correct evidence was not retrieved, answer quality cannot be repaired reliably by generation. Evaluation therefore separates ingestion, retrieval, generation, security, and business behavior.

## Dataset format

Each synthetic case contains:

- a natural-language query;
- expected relevant chunk IDs;
- forbidden chunk IDs;
- optional source, person, and time filters;
- an expected answer or explicit insufficient-evidence label;
- required supporting citation IDs.

## Retrieval metrics

- Recall@5 and Recall@10.
- Mean Reciprocal Rank.
- nDCG for graded relevance.
- Forbidden-result rate; target is exactly zero.
- P50 and P95 query latency on the reference laptop.

## Generation metrics

- Claim faithfulness to retrieved context.
- Citation correctness and completeness.
- Correct abstention when evidence is absent.
- Separation of people, dates, and conversations.
- Resistance to instructions embedded in source content.

## Indexing metrics

- Import success and failure counts by parser.
- Added, modified, unchanged, deleted event accuracy.
- Reprocessing after interruption.
- Content and permission freshness once continuous sync exists.

## Initial gates

- Phase 1: deterministic import and deletion tests pass.
- Phase 2: no forbidden retrievals; baseline Recall@10 recorded.
- Phase 3: hybrid retrieval exceeds lexical and vector-only baselines on the project set.
- Phase 4: every factual answer is cited or explicitly unsupported.

## Phase 2 baseline

- Algorithm: deterministic BM25 over paragraph-based chunks.
- Chinese tokenization: CJK unigrams and bigrams; Latin text uses lowercase word tokens.
- Weak-match control: at least 35% of distinct query terms must occur in a candidate.
- Smoke baseline: Recall@5 = 1.0, Recall@10 = 1.0, MRR = 1.0 on the initial two-query set.
- Scope isolation: a query restricted to one source returns zero results from other sources.
- The initial fixture is deliberately small; expand it before using these numbers for model or
  product comparisons.

## Expanded Chinese benchmark

The version-one synthetic benchmark contains 15 fictional documents and 25 natural-language
queries. It covers path security, read-only behavior, change events, rollback, encodings, SQLite,
crash recovery, lexical search, evaluation, privacy, canonical documents, scan limits, and the
local console. Two documents live in a separate restricted source to verify source isolation.

Observed lexical baseline on 2026-09-07:

- Recall@5: 0.46
- Recall@10: 0.46
- MRR: 0.38
- Forbidden-result rate: 0.0
- P50 latency: approximately 0.36 ms
- P95 latency: approximately 0.54 ms

The large drop from the two-query smoke set is expected and useful. Exact terminology performs
well, while colloquial paraphrases and synonyms expose the semantic limitations of lexical-only
retrieval. The test gate is intentionally below the product target and exists to detect regression;
phase 3 hybrid retrieval must improve this expanded benchmark without increasing forbidden results.

After technical-token normalization, question-noise removal, title weighting, and IDF-weighted
informative-term coverage were added without changing the fixture:

- Recall@5: 0.66 (previously 0.46)
- Recall@10: 0.66 (previously 0.46)
- MRR: 0.56 (previously 0.38)
- Forbidden-result rate: 0.0 (unchanged)
- P50 latency: approximately 0.39 ms
- P95 latency: approximately 0.49 ms

The remaining misses are retained as phase 3 semantic targets rather than encoded into a
benchmark-specific synonym table.
