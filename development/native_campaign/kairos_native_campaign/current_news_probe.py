"""Finite diagnostic of the existing GDELT primary source, never admission.

GDELT's seendate is an index-observation timestamp, not proof of the publisher's
publication time. The existing parser output is therefore diagnostic only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import ssl
import time
from pathlib import Path

import aiohttp
from kairos_text.config import TextSettings
from kairos_text.sources.gdelt import GDELT_DOC_URL, GDELTSource

from .current_capture import _new_capture_dir, _write_raw, _write_receipt


async def probe(output: Path) -> dict:
    directory, identity = _new_capture_dir(output)
    query = TextSettings(_env_file=None).gdelt_query
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": "3",
        "format": "json",
        "timespan": "15min",
        "sort": "DateDesc",
    }
    started = time.time_ns() // 1_000_000
    status, category, items, body = None, None, [], b""
    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=15, sock_read=15)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(
                GDELT_DOC_URL, params=params, allow_redirects=False, ssl=ssl.create_default_context()
            ) as response:
                status = response.status
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    if len(chunks) + len(chunk) > 128 * 1024:
                        raise ValueError("BODY_BOUND_EXCEEDED")
                    chunks.extend(chunk)
                body = bytes(chunks)
                if status == 200:
                    payload = json.loads(body)
                    items = GDELTSource.parse(payload)
                else:
                    category = "HTTP_STATUS_NOT_SUCCESS"
    except Exception as exc:
        category = type(exc).__name__
    received = time.time_ns() // 1_000_000
    # A failed/empty response is still retained, not relabeled as a quiet feed.
    if body:
        _write_raw(directory, "gdelt.raw", body)
    receipt = {
        "schema": "kairos.current-gdelt-source-diagnostic.v1",
        "capture_id": identity,
        "endpoint": GDELT_DOC_URL,
        "params": params,
        "started_ms": started,
        "received_ms": received,
        "status": status,
        "error_category": category,
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "raw_bytes": len(body),
        "items": [
            {"title": x.title, "url": x.url, "index_seen_at": x.published_at.isoformat()} for x in items
        ],
        "time_semantics": "INDEX_SEEN_TIME_NOT_PUBLISHER_PUBLICATION_PROOF",
        "source_admission": False,
        "model_calls": 0,
        "retries": 0,
        "redirects": 0,
    }
    _write_receipt(directory, "gdelt-diagnostic.receipt.json", receipt)
    return {
        "receipt_directory": str(directory),
        "status": status,
        "error_category": category,
        "items": len(items),
        "source_admission": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.output))))


if __name__ == "__main__":
    main()
