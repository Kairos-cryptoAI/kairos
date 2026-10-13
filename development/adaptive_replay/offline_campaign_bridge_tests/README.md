# Offline campaign choreography gate

Run from the meta-repository root with Python 3.11 or 3.14:

```text
python -m unittest discover -s development/adaptive_replay/offline_campaign_bridge_tests
```

The isolated fixtures exercise only the new `campaign_shadow_adapter_v1` file.
They do not import the unaccepted adaptive working-tree changes and do not
construct a database, model provider, source client, Risk Manager or venue.

The adapter follows the currently accepted Persistence API. Capture is a
separate pre-cutoff phase: the database stamps actual observation time. A
post-cutoff claim freezes and resolves already saved sources; it cannot create
new early news or backdate receipts. Missing, late, failed and UNKNOWN arms
remain in the exact three-arm denominator. A stranded START is never resent.

Passing these fixtures proves call-order and fail-closed choreography only.
It does not qualify real Pydantic receipts, source authenticity, model quality,
full-path matched A/B, economic results, or native service integration. The
coordinator unconditionally requires explicit offline-test mode.

The historical development-replay lock still pins an older Persistence API.
It is intentionally not rewritten by this gate. A separate accepted campaign
environment, real typed receipt factory, source scheduler, and durable Risk
shadow evidence are required before any native campaign enrollment. Existing
frozen campaigns, plans, source fingerprints and ledgers remain unchanged.

All trading-readiness flags remain false and strategy policy is `REJECT_ALL`.
