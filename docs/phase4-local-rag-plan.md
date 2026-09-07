# Phase 4 Local RAG and Traceable Answers

## Goal

Turn authorized hybrid-search evidence into a local answer whose sources can be inspected. No
retrieved text may become a system instruction, trigger a tool, or cause a network request.

## First vertical slice

The initial path is:

```text
question -> scoped hybrid retrieval -> evidence gate -> deduplicated context budget
         -> loopback-only ChatModel -> answer plus independently constructed citations
```

Implemented foundations:

- `ChatModel` is a provider-independent interface.
- `LocalOpenAIChatModel` talks directly to an HTTP loopback address, does not use a proxy, does not
  follow redirects, limits response size, and has no cloud fallback.
- `ContextBuilder` reloads full chunks by `(source_id, chunk_id)`, deduplicates identical content,
  enforces chunk and character limits, and creates citations separately from model output.
- `RAGService` applies a deterministic evidence gate. With no accepted evidence it abstains without
  calling the model.
- Retrieved text is placed only in the user message beneath an explicit untrusted-source boundary;
  the system policy forbids tools, networking, instruction following, and unsupported claims.
- The CLI `ask` command exposes the complete service path for a local OpenAI-compatible runtime.

## Completed local runtime

- Runtime: Ollama 0.33.3 on Windows, serving only through its local API.
- Model: `qwen3:4b-instruct-2507-q4_K_M`, 2.5 GB download and about 3.2 GB loaded size.
- Hardware observation: 100% GPU placement on the RTX 3060 Laptop GPU; total system GPU memory in
  use was approximately 4.87 GiB of 6 GiB during measurement.
- Budgeting: conservative tokenizer-independent token estimation bounds context before generation;
  exact prompt and completion counts are captured from the OpenAI-compatible response.
- Filters: source, file type, and update time apply to lexical and vector retrieval before context
  selection or generation. Queries are NFKC-normalized, control characters removed, whitespace
  collapsed, and length limited.
- Validation: every factual sentence must use an in-range source marker and pass lexical or semantic
  support against the cited chunk. A failed check becomes an explicit insufficient-evidence answer.

## Real-model benchmark

Eight synthetic cases cover path security, read-only behavior, crash recovery, offline behavior,
derived deletion, citation fields, prompt injection, and an unsupported weather question.

- Passed: 8/8.
- Warm end-to-end P50: approximately 319 ms.
- Warm end-to-end P95: approximately 895 ms.
- Observed prompt sizes: 171 to 468 tokens for generated cases.
- Unsupported case: rejected before generation with zero generation time and no model call.
- Prompt-injection case: returned a cited refusal and caused no tool or network action.

## Deferred work

1. Expand the answer benchmark beyond eight synthetic cases and add conflicting-source cases.
2. Add streaming and time-to-first-token measurement if the user interface needs it.
3. Add the grounded-answer flow to the visual console in phase six.
4. Run larger-corpus, long-duration, CPU fallback, and fault-injection tests in phase seven.

## Acceptance criteria

- Every returned citation maps to a chunk in the authorized source snapshot.
- Empty or low-confidence evidence never invokes the chat model.
- The runtime rejects non-loopback endpoints and never redirects to a remote host.
- Retrieved instructions cannot invoke tools or networking because no such capability is exposed.
- Factual answers cite supplied evidence; unsupported questions explicitly abstain.
- The entire path works with networking disabled after model installation.

## Current assumptions and risks

- Ollama is installed as the selected local OpenAI-compatible runtime; llama.cpp remains a
  replaceable alternative behind the same interface.
- The preflight counter intentionally overestimates mixed Chinese/Latin tokens; exact usage is
  recorded after generation but Ollama does not expose a tokenizer preflight through this adapter.
- Model-generated citation syntax is not trusted; citation objects always come from the retrieval
  and storage layers.
- Lexical/semantic support checks reduce unsupported prose but are not a formal entailment proof;
  broader adversarial evaluation remains ongoing safety work.
