# 7. Current model APIs and reproducible local verification

Date: 2026-08-12 · Status: accepted · Revises the model identifiers in ADR-0005.

## Context

The original architecture named GPT-5.5 and used editable/pip-oriented local setup. The runtime
now targets newer model APIs, and coordinated changes span eleven Python repositories. Floating
Git dependencies and CI-only feedback made cross-repository verification harder to reproduce on
the Windows development workstation.

## Decision

Use the model routing implemented by `kairos-llm`:

- DeepSeek-V4-Flash and DeepSeek-V4-Pro use the official OpenAI-compatible Chat Completions API,
  explicit non-thinking mode and local strict Pydantic validation;
- GPT-5.6 Sol handles `high` and `xhigh` work through the OpenAI Responses API with SDK-native
  Pydantic structured parsing.

Use `uv` 0.12.3, a `.python-version` development baseline of 3.11, committed `uv.lock` files,
and full commit SHA pins for internal Git sources. Python CI covers Linux 3.11/3.14 and Windows
3.11. Cross-repository changes land on `main` in dependency order only after dependency SHAs
and consumer lockfiles are stable.

The meta-repository owns a declarative repository manifest and a Windows-first PowerShell
runner. Without Docker or credentials it executes lock verification, Ruff lint/format, mypy,
Bandit, network-free unit tests and package builds. It reports but never cleans dirty worktrees,
and it does not read `.env` files.

## Consequences

The local gate and GitHub matrices use the same locked inputs and make cross-repository drift
visible before merge. Exact Git SHA pins improve reproducibility but require deliberate merge
ordering and re-locking consumers.

These checks do not establish production readiness. Docker-backed persistence integration,
durable service-runtime inbox/outbox wiring, external provider/live EVEDEX tests, canaries,
soak/reconnect testing and operational recovery remain separate gates.
