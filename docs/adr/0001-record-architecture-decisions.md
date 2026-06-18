# 1. Record architecture decisions

Date: 2026-06-05 · Status: accepted

## Context
Kairos is a multi-repo system with non-obvious safety trade-offs. We want the reasoning
behind structural choices to be discoverable.

## Decision
We use Architecture Decision Records (Michael Nygard format). Each significant decision is
a numbered markdown file in `docs/adr/`.

## Consequences
New engineers can read *why*, not just *what*. ADRs are append-only; superseding decisions
reference the ones they replace.
