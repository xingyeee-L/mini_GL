# ADR 0003: Local Qwen grounded generation

## Status

Accepted on 2026-09-08.

## Decision

Use Ollama's OpenAI-compatible loopback API with the pinned
`qwen3:4b-instruct-2507-q4_K_M` model as the first local generation runtime. Keep the core behind a
`ChatModel` interface and reject non-loopback hosts, HTTPS, credentials, query parameters, redirects,
oversized responses, and malformed replies.

Construct citations from authorized database rows, not from model metadata. Require every factual
sentence to carry an in-range source marker and pass deterministic lexical or local-embedding
support against its cited evidence. When retrieval or validation fails, return an explicit
insufficient-evidence response.

## Evidence

The 2.5 GB model loaded fully on the RTX 3060 Laptop GPU with an observed 3.2 GB runtime size. The
eight-case synthetic RAG benchmark passed 8/8 with an end-to-end P50 of about 319 ms and P95 of about
895 ms. The unsupported question was rejected before model invocation, and prompt-injection text
caused no action.

## Consequences

- The application works without network access after model installation.
- Ollama is replaceable by another loopback OpenAI-compatible runtime.
- Exact post-generation token usage is recorded; preflight uses a conservative local estimator.
- Citation support checks reduce hallucination risk but do not prove logical entailment.
- The model has no tool, shell, filesystem, or outbound-network capability.
