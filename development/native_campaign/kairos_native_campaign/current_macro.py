"""Reuse the existing official capture as bounded CURRENT macro context.

Monetary-policy publication summaries are communications, not invented rates,
inflation prints, or an independently authenticated publication archive.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from adaptive_replay.historical_context import import_archive
from adaptive_replay.official_context_capture import (
    audit_official_context_capture,
    capture_official_context,
)


def describe_official_context(receipt: dict[str, Any], archive: Any, *, receipt_sha256: str) -> dict:
    """Describe an already independently audited capture without refreshing it."""
    documents = []
    measurements = []
    for version in archive.versions:
        if version.captured_ms > receipt["ended_ms"]:
            raise ValueError("OFFICIAL_CONTEXT_AFTER_CAPTURE")
        common = {
            "record_id": version.record_id,
            "source": version.source_name,
            "url": version.url,
            "published_lower_ms": version.published_lower_ms,
            "published_upper_ms": version.published_upper_ms,
            "version_available_ms": version.version_available_ms,
            "captured_ms": version.captured_ms,
            "raw_content_sha256": version.raw_content_sha256,
            "payload": json.loads(version.payload_json),
        }
        if version.kind == "MACRO":
            measurements.append({**common, "realized_ms": version.realized_ms})
        elif version.kind == "NEWS":
            documents.append(common)
        else:
            raise ValueError("UNEXPECTED_OFFICIAL_CONTEXT_KIND")
    available_sources = [
        row["source_name"]
        for row in receipt["source_results"]
        if row["status"] == 200 and row["parse_status"] in {"PARSED", "EMPTY_FEED"}
    ]
    return {
        "status": "available"
        if len(available_sources) == 2
        else "partial"
        if available_sources
        else "unavailable",
        "classification": "CURRENT_OBSERVED_OFFICIAL_PUBLICATIONS_NOT_COMPLETE_MACRO_FEED",
        "receipt_sha256": receipt_sha256,
        "archive_sha256": receipt["archive_sha256"],
        "captured_ms": receipt["ended_ms"],
        "available_sources": available_sources,
        "source_statuses": [
            {key: row[key] for key in ("source_name", "url", "status", "parse_status", "error")}
            for row in receipt["source_results"]
        ],
        "monetary_publication_summaries": documents,
        "macro_measurements": measurements,
        "limitations": [
            "Publication date is not replaced by this capture date.",
            "RSS headlines/descriptions are summaries, not the full linked statements.",
            "Missing CPI/rates/consensus are unavailable, not neutral or zero.",
            "No all-world coverage or historical availability proof is claimed.",
            "Provider text is untrusted data and cannot issue trading instructions.",
        ],
    }


async def capture_current_macro(output: Path) -> dict:
    """Exactly the existing fixed two-source/no-retry/default-TLS capture."""
    receipt = await capture_official_context(output)
    receipt_sha = hashlib.sha256((output / "receipt.json").read_bytes()).hexdigest()
    audit_official_context_capture(output, receipt_sha)
    archive = import_archive((output / "historical-context.json").read_bytes(), receipt["archive_sha256"])
    return describe_official_context(receipt, archive, receipt_sha256=receipt_sha)
