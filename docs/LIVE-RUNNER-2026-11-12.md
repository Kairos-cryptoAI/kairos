# Live runner — 2026-11-12

`kairos-autotrader` is added to the workspace manifest as the thirteenth Python
repository. It is the first component that places real orders on EVEDEX PROD. This note
records what that does and does not establish.

## What exists

- A single process that scans, reviews, sizes, enters with exchange-side stop and target,
  manages and accounts positions on EVEDEX PROD, at 1x leverage, inside hard code ceilings
  (capital basis 100 USDT, risk per trade 1 USDT, three open positions).
- Layer code from Text Scouts, Router, Aggregator, Macro Strategist, Risk Manager and the
  Strategy Engine is executed unchanged in each repository's own locked environment.
- The repository passes the workspace gates: locked dependencies, Ruff, Ruff format, mypy,
  Bandit, network-free tests and package build.

## Observed on the venue (2026-11-11)

- A market IOC order with attached stop-loss and take-profit was accepted with the API key
  and an EIP-712 signature on chain 42161; TP/SL `side` equals the position side.
- One trade completed entry, protection, exit and balance accounting.
- Model calls answered for candidate review, Text Scouts extraction, Aggregator review and
  the Macro allocation.

## What this does not establish

- No readiness flag changes: `technicalPaperReady`, `paperQualified`, `alphaReady` and
  `liveReady` stay `false`, and `strategyPolicy` stays `REJECT_ALL`.
- No economic claim. One completed trade is not evidence of an edge.
- The runner does not yet pass the strict contracts between layers, does not call
  `LiveRiskEvaluator`, and by default does not require Risk Manager approval. These
  deviations and their removal order are in the runner's `docs/ALIGNMENT.md`.
- The pinned service releases still reject `LIVE`; nothing in this note changes them.
- The repository is a local checkout. It is not pinned in `config/current-release.json`
  because that manifest pins published revisions only.
