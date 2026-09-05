# mini_GL

mini_GL is a local-first personal knowledge retrieval and question-answering project. The first milestone establishes the product boundaries, privacy rules, architecture, data contracts, and a testable Python skeleton.

## Phase 0 status

- Product scope and acceptance criteria are documented.
- The architecture is a modular monolith with replaceable connectors, indexes, and model providers.
- Source data is read-only; derived data must be rebuildable.
- Real chat records and private files are excluded from the repository and from coding-agent context.
- Only synthetic fixtures are used in automated tests.
- No model, vector database, network service, telemetry, or chat-client extraction is implemented yet.

## Safety boundary

The project may later import user-authorized exports from local files, QQ, or WeChat. It must not bypass client encryption, inspect another person's account, modify source data, silently call cloud models, or expose a network service beyond the local machine by default.

## Repository map

```text
docs/                    Product and engineering specifications
src/mini_gl/             Application package
  api/                   Local API boundary
  connectors/            Read-only source adapters
  domain/                Canonical domain models
  generation/            Local LLM interfaces
  indexing/              Lexical/vector indexing interfaces
  normalization/         Source-to-domain transformations
  parsers/               File and export parsers
  retrieval/             Query, fusion, filtering, reranking
  security/              Path, privacy, and policy controls
  storage/               Metadata and derived-data persistence
tests/                   Unit, integration, security, retrieval tests
  fixtures/synthetic/    Fictional data only
data/                    Runtime data; ignored by Git
```

## Local verification

From this directory, with Python 3.11 or newer:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q src tests
```

Development dependencies are declared in `pyproject.toml`, but Phase 0 verification intentionally works with the Python standard library.

## Next milestone

Phase 1 will implement a read-only TXT/Markdown vertical slice: allowlisted directory scan, path validation, SHA-256 change detection, canonical normalization, SQLite sync state, deletion events, and source-preserving tests.

