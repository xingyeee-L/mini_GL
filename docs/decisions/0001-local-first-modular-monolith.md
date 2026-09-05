# ADR 0001: Local-first modular monolith

## Status

Accepted for Phase 0.

## Context

The project handles highly sensitive personal data and is developed by a small team. Early microservices would add deployment, networking, observability, and consistency complexity before those costs are justified.

## Decision

Use one local Python application organized into modules with typed interfaces. Keep source data read-only, derived data local and rebuildable, and model providers replaceable.

## Consequences

- Development and debugging remain simple.
- Privacy boundaries are easier to inspect.
- Interfaces permit later process separation.
- CPU-heavy parsing and model inference may eventually require workers, but that decision will follow measurements.

