# mini_GL Product Requirements

## Product statement

mini_GL helps one user search and ask questions over authorized local knowledge while keeping source data local, read-only, traceable, and removable.

## Primary user

A technically capable individual who wants to retrieve knowledge from personal files and user-authorized chat exports on one computer.

## User problem

Useful context is fragmented across documents and conversations. Existing search often depends on exact keywords, and general-purpose AI tools may require manual uploads or expose sensitive content to remote services.

## MVP goal

Deliver a local pipeline that imports TXT and Markdown from an explicitly selected directory, builds lexical and vector-ready records, retrieves relevant passages, and later generates locally grounded answers with citations.

## Functional requirements

- FR-01: Register an explicit local data-source root.
- FR-02: Scan only allowlisted roots and supported file extensions.
- FR-03: Read source files without modifying their bytes, names, timestamps, or locations.
- FR-04: Normalize imported content into canonical documents and chunks.
- FR-05: Detect additions, modifications, unchanged files, and deletions by stable identity and hash.
- FR-06: Preserve source path, timestamps, offsets, and citation metadata.
- FR-07: Support lexical retrieval before local-LLM integration.
- FR-08: Support local embeddings, reranking, and generation behind provider interfaces.
- FR-09: Return answers with inspectable source citations.
- FR-10: Remove all derived data for a selected source without touching originals.

## Non-functional requirements

- NFR-01 Privacy: no telemetry or cloud-model fallback.
- NFR-02 Security: path authorization occurs before file access.
- NFR-03 Reliability: interrupted imports are retryable and idempotent.
- NFR-04 Traceability: every chunk and answer maps to an original source.
- NFR-05 Recoverability: indexes can be rebuilt from authorized sources.
- NFR-06 Testability: automated tests use synthetic data only.
- NFR-07 Portability: model and storage providers are replaceable.

## Phase 0 acceptance criteria

- [x] Repository-level privacy and development instructions exist.
- [x] Product scope, architecture, threat model, data contracts, and evaluation plan exist.
- [x] Python package boundaries match the documented architecture.
- [x] Canonical document, message, chunk, and citation models are defined.
- [x] Path-boundary helper rejects traversal and disallowed extensions.
- [x] Automated tests use only synthetic fixtures.
- [x] Runtime/private data paths are ignored by Git.
- [x] The skeleton compiles and standard-library tests pass.

## Out of scope for the MVP

- Bypassing QQ or WeChat encryption or access controls.
- Reading another person's account without authorization.
- Modifying source files or writing into chat-client storage.
- Sending messages or executing arbitrary shell commands.
- Public network deployment or multi-tenant administration.
- Automatic cloud inference fallback.

## Open decisions

- Exact local embedding, reranking, and generation models will be selected by benchmark.
- The first persistent lexical/vector stores will be selected in Phases 2 and 3.
- QQ/WeChat formats will enter through a documented intermediate export schema.

