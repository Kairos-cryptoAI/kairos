from __future__ import annotations

import unittest

if __package__:
    from . import ops_source_feed as feed
else:
    import ops_source_feed as feed


KEY_A = "a" * 64
KEY_B = "b" * 64
NOW = 1_800_000_000_000


class OpsSourceFeedTests(unittest.TestCase):
    def normalize(
        self,
        source: feed.Source,
        state: str,
        key: str = KEY_A,
        *,
        age: int = 0,
        recovery_kind: str | None = None,
        **kwargs,
    ):
        return feed.normalize_event(
            feed.SourceEvent(source, state, key, NOW - age, recovery_kind),
            now_ms=NOW,
            freshness_bound_ms=60_000,
            **kwargs,
        )

    def test_dedupe_identity_is_stable_and_state_scoped(self) -> None:
        first = self.normalize(feed.Source.VENUE_OBSERVATION, "UNKNOWN_OUTCOME")
        same = self.normalize(feed.Source.VENUE_OBSERVATION, "UNKNOWN_OUTCOME")
        different_source_event = self.normalize(feed.Source.VENUE_OBSERVATION, "UNKNOWN_OUTCOME", KEY_B)
        changed_state = self.normalize(feed.Source.VENUE_OBSERVATION, "MISSED_RUN_DEADLINE")
        self.assertEqual(first.event_id, same.event_id)
        self.assertNotEqual(first.event_id, different_source_event.event_id)
        self.assertNotEqual(first.event_id, changed_state.event_id)
        self.assertEqual(len(first.event_id), 64)

    def test_fixed_severity_and_business_categories_muted_by_default(self) -> None:
        technical = self.normalize(feed.Source.VENUE_OBSERVATION, "UNKNOWN_OUTCOME")
        campaign = self.normalize(feed.Source.CAMPAIGN, "BUDGET_BLOCKED")
        risk = self.normalize(feed.Source.RISK, "REJECTED")
        candidate = self.normalize(feed.Source.CANDIDATE, "VETO")
        self.assertEqual(technical.severity, feed.Severity.CRITICAL)
        self.assertTrue(technical.enabled)
        self.assertEqual(campaign.severity, feed.Severity.WARNING)
        self.assertFalse(campaign.enabled)
        self.assertFalse(risk.enabled)
        self.assertFalse(candidate.enabled)
        explicitly_enabled = self.normalize(
            feed.Source.CAMPAIGN,
            "BUDGET_BLOCKED",
            enabled_sources=frozenset({feed.Source.CAMPAIGN}),
        )
        self.assertTrue(explicitly_enabled.enabled)

    def test_absent_and_non_alerting_source_states_produce_no_candidate(self) -> None:
        self.assertIsNone(None)
        self.assertIsNone(self.normalize(feed.Source.CAMPAIGN, "ALLOW"))
        self.assertIsNone(self.normalize(feed.Source.CANDIDATE, "ALLOW"))
        self.assertIsNone(
            self.normalize(
                feed.Source.BACKUP_RESTORE,
                "PASS_FRESH_BACKUP_TWO_ISOLATED_RESTORES",
                age=60_001,
            )
        )
        with self.assertRaisesRegex(feed.FeedError, "SOURCE_STATE_UNSUPPORTED"):
            self.normalize(feed.Source.RISK, "UNTRUSTED_FREE_TEXT")

    def test_campaign_stale_is_derived_only_from_explicit_freshness_bound(self) -> None:
        fresh = self.normalize(feed.Source.CAMPAIGN, "UNKNOWN", age=60_000)
        stale = self.normalize(feed.Source.CAMPAIGN, "UNKNOWN", age=60_001)
        self.assertEqual(fresh.state, feed.State.CAMPAIGN_UNKNOWN)
        self.assertEqual(stale.state, feed.State.CAMPAIGN_STALE)
        self.assertEqual(stale.severity, feed.Severity.WARNING)

    def test_no_payload_forwarding_redaction_and_unknown_latch_semantics(self) -> None:
        candidate = self.normalize(feed.Source.CAMPAIGN, "UNKNOWN")
        serialized = repr(candidate)
        self.assertNotIn("secret", serialized.lower())
        self.assertNotIn("token", serialized.lower())
        self.assertNotIn(KEY_A, serialized)
        self.assertEqual(
            candidate.message,
            "Research campaign outcome remains unknown; no retry is authorized.",
        )
        self.assertFalse(candidate.automatic_resend)
        self.assertEqual(candidate.dispatch_state, "NOT_DISPATCHED")

    def test_r7_success_requires_exact_recovery_kind(self) -> None:
        with self.assertRaisesRegex(feed.FeedError, "RECOVERY_KIND_UNSUPPORTED"):
            self.normalize(feed.Source.BACKUP_RESTORE, "PASS_NEW_NONTRADING_GENERATION")
        with self.assertRaisesRegex(feed.FeedError, "RECOVERY_KIND_UNSUPPORTED"):
            self.normalize(
                feed.Source.BACKUP_RESTORE,
                "PASS_NEW_NONTRADING_GENERATION",
                recovery_kind="OTHER_RECOVERY",
            )
        candidate = self.normalize(
            feed.Source.BACKUP_RESTORE,
            "PASS_NEW_NONTRADING_GENERATION",
            recovery_kind="R7_REDIS_TRANSPORT_RECOVERY",
        )
        self.assertEqual(candidate.state, feed.State.BACKUP_RESTORE_SUCCEEDED)

    def test_bounds_and_bad_identity_fail_closed(self) -> None:
        with self.assertRaisesRegex(feed.FeedError, "FRESHNESS_BOUND_INVALID"):
            feed.normalize_event(
                feed.SourceEvent(feed.Source.CAMPAIGN, "UNKNOWN", KEY_A, NOW),
                now_ms=NOW,
                freshness_bound_ms=0,
            )
        with self.assertRaisesRegex(feed.FeedError, "SOURCE_KEY_INVALID"):
            self.normalize(feed.Source.CAMPAIGN, "UNKNOWN", "not-a-digest")
        with self.assertRaisesRegex(feed.FeedError, "TIMESTAMP_INVALID"):
            feed.normalize_event(
                feed.SourceEvent(feed.Source.CAMPAIGN, "UNKNOWN", KEY_A, True),
                now_ms=NOW,
                freshness_bound_ms=60_000,
            )

    def test_admission_boundary_is_offline_and_no_dispatch(self) -> None:
        boundary = feed.source_admission_boundary()
        self.assertEqual(boundary["mode"], "OFFLINE_TYPED_FEED_ONLY")
        self.assertFalse(boundary["reads_sources"])
        self.assertFalse(boundary["writes_journal"])
        self.assertFalse(boundary["dispatches"])
        self.assertTrue(boundary["source_binding_required"])
        self.assertEqual(boundary["unknown_outcome_policy"], "PRESERVE_PRODUCER_LATCH_NO_RETRY")


if __name__ == "__main__":
    unittest.main()
