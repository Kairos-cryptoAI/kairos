"""Publish public research receipts and byte-exact pre-format source snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).parents[1]
    result = json.loads((args.runtime / "result.json").read_text())
    if result["state"] != "COMPLETED" or result["real_model_calls"] != 12:
        raise ValueError("only complete known-cost paired results may be published")
    args.destination.mkdir(parents=True, exist_ok=False)
    snapshots = args.destination / "sealed-sources"
    snapshots.mkdir()
    for name, expected in result["sources"]["experiment_scripts_sha256"].items():
        payload = (source / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("experiment source changed before snapshot publication")
        with (snapshots / f"{name}.txt").open("xb") as stream:
            stream.write(payload)
    allowed = [
        "result.json",
        "before.json",
        "sealed-plan.json",
        "seal.json",
        "requests.json",
        "reviews.jsonl",
        "worker-start.json",
        "worker-result.json",
        "gateway-source.json",
        "attempts.jsonl",
        "local-budget.jsonl",
    ]
    allowed += sorted(p.name for p in args.runtime.glob("*-input-integrity.json"))
    allowed += sorted(p.name for p in args.runtime.glob("*-ledger.json"))
    hashes = {}
    for name in allowed:
        payload = (args.runtime / name).read_bytes()
        with (args.destination / name).open("xb") as stream:
            stream.write(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    with (args.destination / "public-receipt-files.json").open(
        "x", newline="\n"
    ) as stream:
        json.dump(
            {
                "schema": "kairos.market-review.public-receipts.v1",
                "files_sha256": hashes,
                "secrets_included": False,
                "raw_api_transport_or_auth_headers_included": False,
            },
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    print(
        f"published_public_files={len(hashes)} sealed_source_snapshots={len(result['sources']['experiment_scripts_sha256'])}"
    )


if __name__ == "__main__":
    main()
