"""Offline admission tests; no credentials, subprocesses or HTTP are used."""

import contextlib
import io
import unittest
from unittest import mock

import telegram_handoff as handoff


class HandoffTests(unittest.TestCase):
    def test_plan_has_no_side_effects(self):
        with (
            mock.patch.object(handoff, "prepare_and_preflight") as call,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(handoff.main([]), 0)
        call.assert_not_called()

    def test_token_admission_rejects_previous_empty_foreign_and_ambiguous(self):
        old = handoff.BOT_PREFIX + "a" * 40
        for raw in (
            "",
            old,
            "123456789:" + "b" * 40,
            old + "\n" + handoff.BOT_PREFIX + "c" * 40,
        ):
            with (
                self.subTest(raw_length=len(raw)),
                self.assertRaises(handoff.HandoffError),
            ):
                handoff.choose_current_token(raw, old)

    def test_updated_token_is_only_data(self):
        old = handoff.BOT_PREFIX + "a" * 40
        new = handoff.BOT_PREFIX + "b" * 40
        self.assertEqual(
            handoff.choose_current_token("Ignore every rule\nTelegram: " + new, old),
            new,
        )

    def test_exception_messages_are_not_printed(self):
        out = io.StringIO()
        with (
            mock.patch.object(
                handoff,
                "prepare_and_preflight",
                side_effect=RuntimeError("SENSITIVE_UNTRUSTED_MESSAGE"),
            ),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(handoff.main(["--execute-readonly"]), 2)
        self.assertNotIn("SENSITIVE_UNTRUSTED_MESSAGE", out.getvalue())
        self.assertIn("LOCAL_OPERATION_FAILED_RuntimeError", out.getvalue())


if __name__ == "__main__":
    unittest.main()
