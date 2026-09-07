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

## Remaining work

1. Select and install one local instruct model that fits the reference 6 GB GPU and CPU fallback.
2. Replace the character approximation with the selected model tokenizer and a measured token
   budget.
3. Add deterministic query rewriting and explicit source/type/time filters to `ask`.
4. Validate citation markers against the supplied citation set and evaluate claim support.
5. Add an answer benchmark covering correct answers, abstention, conflicting evidence, citation
   completeness, and prompt injection.
6. Record retrieval, time-to-first-token, total generation latency, memory, and failure behavior.
7. Add the grounded-answer flow to the local visual console after the CLI path is stable.

## Acceptance criteria

- Every returned citation maps to a chunk in the authorized source snapshot.
- Empty or low-confidence evidence never invokes the chat model.
- The runtime rejects non-loopback endpoints and never redirects to a remote host.
- Retrieved instructions cannot invoke tools or networking because no such capability is exposed.
- Factual answers cite supplied evidence; unsupported questions explicitly abstain.
- The entire path works with networking disabled after model installation.

## Current assumptions and risks

- The first runtime will expose an OpenAI-compatible loopback endpoint; Ollama and llama.cpp are
  candidates, but neither is currently installed on the reference machine.
- Character limits are a conservative temporary control, not a final token budget.
- Model-generated citation syntax is not trusted; citation objects always come from the retrieval
  and storage layers.
- A model can still produce unsupported prose, so claim-level evaluation remains a phase blocker.
