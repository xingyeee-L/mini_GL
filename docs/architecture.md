# Architecture

## Architectural style

mini_GL begins as a modular monolith. Each module has a narrow interface, but deployment remains one local application until measured scale or isolation requirements justify another process.

## Data flow

```text
Authorized sources
    -> connector scan and change events
    -> parser
    -> canonical normalization
    -> metadata/sync state
    -> lexical and vector indexes
    -> filtered hybrid retrieval
    -> reranking and context packing
    -> local generation
    -> answer with citations
```

## Modules

### connectors

Read-only adapters enumerate authorized source objects and emit change events. A connector never writes to its source.

### parsers

Parsers convert bytes or export records into source-shaped parsed objects. They do not know about indexes or models.

### normalization

Normalization maps source-shaped objects to canonical `SourceDocument`, `ChatMessage`, and `SearchChunk` records.

### storage

Storage owns source registration, sync cursors, canonical metadata, tombstones, migrations, and transactions.

### indexing

Indexing owns lexical and vector representations. Derived indexes are disposable and rebuildable.

### retrieval

Retrieval parses deterministic filters, retrieves lexical/vector candidates, applies access scope, fuses results, reranks, deduplicates, and selects context.

### generation

Generation calls a local model through a typed interface. Retrieved content is untrusted context. The result includes citations or an explicit insufficient-evidence outcome.

### security

Security centralizes path validation, source authorization, privacy-safe logging, prompt-injection policy, and future action authorization.

### api

The future local API exposes source management, indexing status, search, question answering, and derived-data deletion. It binds to loopback by default.

## Trust boundaries

1. User-selected source files are sensitive and untrusted.
2. Parsed text is sensitive and may contain prompt injection.
3. Derived databases and indexes are sensitive.
4. The local model receives only filtered context.
5. Browser clients are untrusted even when the API listens on loopback.
6. External networks are outside the default operating boundary.

## Key decisions

- Local-first and offline-capable after installation.
- Read-only connectors and rebuildable derived data.
- Canonical contracts between ingestion and retrieval.
- Pre-generation access filtering.
- Hybrid retrieval rather than vector-only search.
- No agent actions until retrieval, citations, and security tests are stable.

