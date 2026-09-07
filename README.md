# mini_GL

mini_GL is a local-first personal knowledge retrieval and question-answering project. The first milestone establishes the product boundaries, privacy rules, architecture, data contracts, and a testable Python skeleton.

## Phase 1 status

- Explicit local source roots can be registered through the CLI.
- TXT and Markdown are scanned through extension, size, depth, and path-boundary policies.
- Symbolic links and Windows reparse points fail closed.
- UTF-8, BOM-marked UTF-16, and GB18030 content is normalized into `SourceDocument`.
- SQLite stores sources, sync runs, file snapshots, documents, and idempotent change events.
- A failed scan never advances the snapshot or emits false deletion events.
- No model, vector index, network service, telemetry, or chat-client extraction is implemented yet.

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

## Phase 1 CLI

The default database is `data/mini_gl.sqlite3`. Start with a disposable directory containing
only non-sensitive test files:

```powershell
$env:PYTHONPATH = "src"
python -m mini_gl register C:\path\to\authorized-test-files
python -m mini_gl sync <source-id>
python -m mini_gl status <source-id>
```

`register` accepts `--max-size` in bytes and `--max-depth`; both may only reduce the built-in
limits of 10 MiB and eight nested directories. `status` reports paths and operational metadata,
but never document content.

## Visual acceptance console

Start the local-only console and open `http://127.0.0.1:8765` in a browser:

```powershell
$env:PYTHONPATH = "src"
python -m mini_gl serve
```

The console registers an explicitly selected test directory, runs the same ingestion service as
the CLI, and displays event counts, file paths, sizes, shortened hashes, and run status. It never
returns document contents to the browser, requires a per-process request token, and only binds to
the loopback interface.

Development dependencies are declared in `pyproject.toml`, but Phase 0 verification intentionally works with the Python standard library.

## Next milestone

Phase 2 provides a rebuildable BM25 lexical index with lowercase word tokens and Chinese
unigrams/bigrams. Search preserves stable chunk and document IDs, source paths, snippets, file
types, timestamps, scores, and measured query latency.

```powershell
python -m mini_gl index <source-id>
python -m mini_gl search "安全边界" --source-id <source-id>
```

The search command also supports `--file-type`, `--updated-after`, and `--limit`. The visual
console exposes the same indexing and search service without sending data over the network.

## Phase 3 engineering slice

The first hybrid-search slice adds a typed local embedding boundary, persistent vector records,
cosine search, reciprocal-rank fusion, and a replaceable reranker. Its dependency-free provider is
for plumbing and privacy verification only; it is not presented as a semantic model.

```powershell
python -m mini_gl vector-index <source-id>
python -m mini_gl hybrid-search <source-id> "断电后如何恢复"
```

After downloading the pinned BGE weights to `models/bge-small-zh-v1.5`, select the real provider:

```powershell
python -m mini_gl vector-index <source-id> --provider bge-small-zh
python -m mini_gl hybrid-search <source-id> "断电后如何恢复" --provider bge-small-zh
```

The provider uses `local_files_only`, disables Hugging Face telemetry, and never falls back to a
hosted inference API.
