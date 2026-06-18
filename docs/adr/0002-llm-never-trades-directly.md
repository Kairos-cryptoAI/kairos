# 2. The LLM never trades directly and never sees raw numbers

Date: 2026-06-05 · Status: accepted

## Context
LLMs hallucinate, stall and occasionally emit nonsense. Letting one place orders or parse
raw tick streams is an unbounded risk.

## Decision
The LLM is an *analytical brain* that only emits structured commands (status + `reason_code`
+ parameters). Raw data is digested into a compact `MarketSnapshot`/`SentimentSignal` before
any model sees it. A separate, deterministic Execution Engine places orders by switching on
the validated `reason_code` only.

## Consequences
Model output is always bounded and auditable. The blast radius of a bad generation is a
single rejected command, never a market order. Adds the Router + Risk Manager indirection.
