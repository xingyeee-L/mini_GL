# Threat Model

## Protected assets

- Original personal files and chat exports.
- Parsed text, embeddings, indexes, caches, and answer history.
- Source paths, contact identities, timestamps, and relationship metadata.
- Local model configuration and future credentials.

## Threat actors

- Accidental user or developer mistakes.
- Malicious content inside an imported document or chat message.
- A malicious webpage calling an unprotected loopback API.
- A compromised dependency or model package.
- Another local account or process with filesystem access.
- An over-permissioned coding or runtime agent.

## Principal risks and controls

### Unintended data egress

Controls: offline-default runtime, no telemetry, no cloud fallback, privacy-safe logs, synthetic development fixtures, dependency review, and explicit network configuration.

### Original data modification

Controls: read-only connectors, no write-back API, source hashes, separate application data directory, and deletion limited to derived records.

### Path traversal or link escape

Controls: canonical path resolution, root containment checks, no symlink/reparse-point traversal by default, extension allowlist, file-size and recursion limits.

### Prompt injection

Controls: retrieved material is untrusted data, generation model has no tools in MVP, external URLs are not opened automatically, system policy is separated from context, and adversarial fixtures are tested.

### Index or log leakage

Controls: full content is absent from normal logs, derived stores inherit user-only filesystem permissions, exports require explicit action, and per-source forgetting deletes all derivatives.

### Stale access state

The first release is single-user but every record carries an access scope. Future multi-user work must enforce access before retrieval and test revocation latency.

### Supply-chain compromise

Controls: locked dependencies, minimal packages, checksums where practical, no runtime package download, documented model provenance, and periodic vulnerability review.

## Security invariants

1. No unapproved path is opened.
2. No original source is modified.
3. No retrieved content becomes an instruction.
4. No private content appears in routine logs or Git.
5. No remote inference occurs silently.
6. Every displayed answer claim can point to a source or be marked unsupported.

## Required security tests

- Traversal and sibling-prefix paths are rejected.
- Symlink/reparse-point escape is rejected where supported.
- Disallowed extensions and oversized files are rejected before parsing.
- Logs do not contain fixture message bodies.
- Deleting derived data never deletes source fixtures.
- Prompt-injection fixtures cannot cause tools or network calls.
- Source revocation removes results before generation.

