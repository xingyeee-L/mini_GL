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
- Synthetic baseline: Recall@5 = 1.0, Recall@10 = 1.0, MRR = 1.0 on the initial two-query set.
- Scope isolation: a query restricted to one source returns zero results from other sources.
- The initial fixture is deliberately small; expand it before using these numbers for model or
  product comparisons.
