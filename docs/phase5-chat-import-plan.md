# Phase 5: Neutral Chat Import

## Trust boundary

The core accepts only a user-supplied, versioned neutral JSON export. It does not open QQ or
WeChat databases, decrypt client storage, inject into client processes, automate login, or call a
network service. Provider-specific converters must run as separate, replaceable preprocessing
tools and produce this neutral contract before core import.

## Version 1.0 contract

Required root fields are `schema_version`, `platform`, `conversation`, and `messages`.
Conversation requires stable `id`, display `title`, and a participant-ID array. Every message
requires a stable ID, sender ID, timezone-aware ISO-8601 timestamp, and a supported message type.
Optional fields are sender display name, text, attachment references, reply target, and withdrawal
marker. Reply targets must exist within the same export.

The importer rejects unknown schema versions, duplicate message IDs, timezone-free timestamps,
unknown message types, exports above 10 MiB, symbolic links/reparse points, malformed UTF-8/JSON,
and files that change while being read.

## Normalization and slicing

Messages are ordered by `(sent_at, id)`. A new search document starts after a gap greater than 30
minutes or after 100 messages. Each document preserves conversation ID, message IDs, participant
IDs, start/end timestamps, platform, and the original export path in metadata. Withdrawn text is
not retained. Attachment values remain inert references and are never opened automatically.

## Acceptance

- Re-importing the same export produces only `unchanged` events.
- A changed window updates deterministically; removed windows become deleted derived records.
- Same-name contacts remain distinct through sender IDs.
- Imported windows can use the existing lexical, vector, hybrid, and grounded-answer pipeline.
- A separate privacy review is required before importing any real export.
