# Canonical Data Contracts

## Design rules

- IDs are stable within a source and globally namespaced.
- UTC timestamps are stored as timezone-aware values.
- Content hashes use SHA-256 over normalized bytes or records.
- Original locations are retained for citation, never rewritten by indexing.
- Optional source-specific fields live in metadata.
- Access scope is present even in single-user mode.

## SourceDocument

| Field | Type | Meaning |
|---|---|---|
| id | string | Stable namespaced document identifier |
| source_type | string | local_file, qq_export, wechat_export, etc. |
| source_uri | string | Canonical local reference |
| title | string | Display title |
| content | string | Normalized text |
| created_at | datetime? | Source creation time |
| updated_at | datetime? | Source modification time |
| participants | string[] | People associated with the item |
| conversation_id | string? | Parent conversation when applicable |
| metadata | object | Source-specific safe metadata |
| content_hash | string | SHA-256 digest |
| access_scope | string | Initial value: owner-only |

## ChatMessage

Required fields: stable ID, platform, conversation ID, sender ID, sent time, message type, access scope, and source reference. Text and attachment references are optional because not every message contains text.

## SearchChunk

A chunk references one source document, preserves chunk order and optional character offsets, and may include a chat time range and participants. Chunk IDs change only when the source content or chunking policy changes.

## Citation

A citation contains source document ID, chunk ID, source URI, display title, and optional character/time span. UI rendering must escape source-provided text.

## ChangeEvent

Connectors emit `created`, `updated`, `unchanged`, or `deleted` with a source ID, object ID, observed version/hash, and observation time. Applying the same event twice must not change the final state.

## Intermediate chat export

Future QQ/WeChat import tools must first produce a versioned neutral JSON document. The core application consumes that schema and does not depend directly on private client databases.

