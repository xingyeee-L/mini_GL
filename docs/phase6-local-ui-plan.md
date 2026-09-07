# Phase 6: Local User Interface

## Product direction

Continue with the loopback browser interface as the first user-facing shell. It reuses the typed
service layer, requires no desktop framework dependency, remains inspectable, and can later be
wrapped by a desktop shell without changing ingestion, retrieval, or generation contracts.

## First vertical slice

- Show local-only network posture, configured embedding model, configured chat model, and
  read-only source policy before any user action.
- Label file-directory and neutral-chat sources distinctly.
- Show last synchronization state plus lexical/vector chunk counts.
- Provide actionable empty and error states without printing document bodies.
- Allow pause/resume. Paused sources reject synchronization and index actions in both UI and
  service logic.
- Allow deletion of application-owned derived data only after typing the source-ID suffix. The
  registered source and original files remain untouched.
- Let users expand a current search result or answer citation in a modal. The modal shows the
  source type, authorized location, access scope, time range, conversation identifier,
  participants, and a bounded plain-text preview. It never interprets source content as HTML.

## Safety invariants

The server binds only to loopback, requires a per-process CSRF token, caps request bodies, sets a
restrictive content security policy, and does not log prompts or document content. Source-derived
labels are inserted using text nodes or escaped before HTML insertion. Destructive derived-data
operations require an explicit, reviewable confirmation and are covered by source-preservation
tests. Source preview is limited to documents in the current authorized snapshot and to 20,000
characters, with every displayed source field rendered through text-only DOM APIs.
