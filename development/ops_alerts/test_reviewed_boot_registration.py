"""Source/AST contracts only; real task qualification is separately receipted."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


SOURCE = Path(__file__).with_name("Register-CurrentReviewedBootTask.ps1")


class ReviewedBootRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_preserved_evidence_and_create_only_registration(self) -> None:
        for guard in (
            "ORIGINAL_HOST_FAILURE_MUST_REMAIN_UNCHANGED",
            "EXACT_IMMUTABLE_PREDECESSOR_BINDING_REQUIRED",
            "REVIEWED_V2_CREATE_ONLY_TARGETS_REQUIRED",
            "[IO.FileMode]::CreateNew",
            "old_task_xml_sha256",
            "-ReviewedV2",
        ):
            self.assertIn(guard, self.source)
        self.assertNotIn("Remove-Item", self.source)
        self.assertNotIn("Unregister-ScheduledTask", self.source)
        self.assertNotIn("Start-ScheduledTask", self.source)
        self.assertNotIn("Register-ScheduledTask -Force", self.source)
        saved = self.source.index("Write-NewBytes $oldXmlPath")
        disabled = self.source.index("Disable-ScheduledTask -TaskName $oldTaskName")
        registered = self.source.index("Register-ScheduledTask -TaskName $newTaskName")
        self.assertLess(saved, disabled)
        self.assertLess(disabled, registered)

    def test_scheduler_metadata_is_nullable_and_identity_based(self) -> None:
        self.assertIn("$null -ne $oldInfo.NextRunTime", self.source)
        self.assertIn("$oldInfo.LastTaskResult -ne 267011", self.source)
        self.assertIn("1999-11-30T00:00:00", self.source)
        self.assertNotIn("FromFileTimeUtc", self.source)
        self.assertIn("[Xml.XmlConvert]::ToTimeSpan", self.source)
        self.assertIn("function Get-IdentitySid", self.source)
        self.assertIn("(Get-IdentitySid $oldUser) -cne $identity.User.Value", self.source)

    def test_native_bootstrap_and_readonly_admission_are_not_replaced(self) -> None:
        self.assertIn("Install-CurrentRuntimeBootTask.ps1", self.source)
        self.assertIn("$bootstrapTemplate", self.source)
        self.assertIn("sys.path.insert(0,r'$DeployRoot/scripts');sys.argv", self.source)
        self.assertIn("SIGNED_STOCK_BOOTSTRAP_TEMPLATE_CHANGED", self.source)
        self.assertIn("$($bindingPath.Replace('\\','/'))", self.source)
        self.assertIn("$bindingHash", self.source)
        self.assertIn("HEALTHY_EXACT_OWNER_REQUIRED_BEFORE_TASK_MUTATION", self.source)
        start = self.source.index("$cli = @($bootPath")
        end = self.source.index("$planCode =", start)
        self.assertNotIn("--execute", self.source[start:end])
        self.assertIn("task_started=$false", self.source)
        self.assertIn("trading_started=$false", self.source)

    def test_signed_sources_and_receipt_remain_mandatory(self) -> None:
        for guard in (
            "SIGNED_CLEAN_META_MAIN_REQUIRED",
            "EXACT_SIGNED_DEPLOY_MAIN_REQUIRED",
            "EXACT_ACCEPTED_NONTRADING_RECEIPT_REQUIRED",
            "TRUSTED_RECEIPT_SIGNATURE_REQUIRED",
            "EXACT_READY_NEVER_RUN_PREDECESSOR_REQUIRED",
            "FRESH_HOST_ACCEPTANCE_DIRECTORY_MUST_BE_ABSENT",
            "hash-object --no-filters",
            "40AF365C6682B73D056A6A274DBFF6B65BE9F827",
        ):
            self.assertIn(guard, self.source)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell AST qualification")
    def test_powershell_ast(self) -> None:
        powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        literal = str(SOURCE.resolve()).replace("'", "''")
        code = (
            "$taskTokens=$null;$taskParseErrors=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{literal}',"
            "[ref]$taskTokens,[ref]$taskParseErrors);"
            "if(@($taskParseErrors).Count -ne 0){exit 2};'AST_OK'"
        )
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode("utf-8-sig").strip(), "AST_OK")


if __name__ == "__main__":
    unittest.main()
