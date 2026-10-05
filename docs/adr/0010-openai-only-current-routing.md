# 10. OpenAI-only defaults and source-specific model qualification

Date: 2026-10-05 · Status: accepted for engineering defaults · Supersedes the
model mapping in ADR-0008; its workload routing and provenance principles remain.

## Decision

The user excludes DeepSeek Flash from default Kairos routing. The current
implementation selects models by workload, not by a global effort alias:

| workload | requested model | effort |
| --- | --- | --- |
| Text extraction | `gpt-6-luna` | `low` |
| Normal candidate review | `gpt-6-luna` | `medium` |
| Conflict candidate review | `gpt-6.1-sol` | `high` |
| Capital allocation | `gpt-6.1-sol` | `xhigh` |

The default provider allow-list is OpenAI-only. Existing optional provider code
is compatibility code, not permission to use it in the approved route. Concrete
routes are owned by `kairos-llm/models.py`; future changes require an explicit
source revision and appropriate new qualification.

## Evidence boundary

This records implemented defaults, not a claim that they are the best available
models or that a historical corpus qualifies them. Quality, cost, latency,
availability, schema validity and freshness must be measured on the exact route
and input contract. Preserve old receipts; do not relabel old models as new ones.

Model request/response provenance, resolved model identity, durable reservation,
actual usage and failure/degradation remain mandatory. A provider outage cannot
enable reviewer-free PAPER trading. The risk and venue gates stay independent.

Existing qualification ceilings and prior spend/reservations are preserved;
this ADR does not grant paid calls, raise budgets, register a campaign, change
readiness or arm PAPER/LIVE.
