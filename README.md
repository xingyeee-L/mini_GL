# mini_GL

mini_GL is a local-first personal knowledge retrieval and question-answering project. It provides safe local-file ingestion, lexical and semantic search, grounded answers from a local Qwen model, source inspection, recovery tooling, and a controlled read-only agent boundary.

## Current status

Phases 0–8 and the first product-facing frontend are complete. The default browser experience now contains a home page, unified search, grounded Q&A, a knowledge library, and an administrative console. Real QQ/WeChat data remains deliberately gated; only fictional fixtures and the provider-neutral chat contract are supported during development.

## Phase 1 status

- Explicit local source roots can be registered through the CLI.
- TXT, Markdown, and security-reviewed DOCX are scanned through extension, size, depth, and path-boundary policies.
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

## Local knowledge workspace

Start the local-only workspace and open `http://127.0.0.1:8765` in a browser:

```powershell
$env:PYTHONPATH = "src"
python -m mini_gl serve
```

The primary experience exposes home, search, grounded Q&A, and knowledge-library views. Source,
index, model, security, and acceptance controls remain available under the integrated console.
The service requires a per-process request token and only binds to the loopback interface. Source
content is returned only through a current authorized snapshot for an explicit preview or answer.

On Windows, `start-mini-gl.cmd` provides the current one-click entry. The equivalent command is:

```powershell
$env:PYTHONPATH = "src"
python -m mini_gl desktop
```

The desktop workspace adds local runtime diagnostics, explicit real-folder authorization,
cross-source search and grounded Q&A, plus verified backup/restore-to-new-path controls. Every
cross-source read is authorized and audited per source, and citations retain their source ID.
DOCX extraction is dependency-free and bounded: it rejects unsafe package paths, XML entities,
compression bombs, macros, ActiveX, and embedded objects, and never follows external links.
PDF, legacy DOC, and other Office formats remain blocked pending separate security review.

Use **Console → Data & Index → Choose folder** to select a real TXT/Markdown/DOCX folder with the
native Windows dialog. Selection only fills the path; registration still requires explicit
authorization, and document contents are read only after the user starts a read-only sync.
Existing sources must be explicitly re-registered before DOCX is added to their allowlist.

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
python -m mini_gl index-sync <source-id> --provider bge-small-zh
python -m mini_gl hybrid-search <source-id> "断电后如何恢复" --provider bge-small-zh
```

The provider uses `local_files_only`, disables Hugging Face telemetry, and never falls back to a
hosted inference API.

`index-sync` preserves unchanged lexical chunks and vectors, embeds only new or changed chunks,
and removes derived vectors for deleted source documents. The database can retain multiple pinned
provider indexes side by side; BGE-small-zh-v1.5 is the phase-three default, while
multilingual-e5-small remains an optional comparison provider.

## Phase 4 grounded-answer slice

The reference setup uses Ollama with the pinned Qwen tag:

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

After the local service starts, ask a question with:

```powershell
python -m mini_gl ask <source-id> "系统如何保护原始文件" `
  --provider bge-small-zh --model qwen3:4b-instruct-2507-q4_K_M
```

The default endpoint is `http://127.0.0.1:11434/v1/chat/completions`. Remote hosts, HTTPS URLs,
credentials, query strings, and redirects are rejected. Answers return citations built from the
authorized database rows rather than trusting citation metadata generated by the model. If the
evidence gate finds nothing usable, the command refuses to answer without invoking the model.
Each factual sentence must also contain an in-range `[来源 N]` marker and pass a lexical or semantic
support check against that cited chunk. Source, file-type, and update-time filters are applied before
generation.
