"""Synthetic offline runner fixtures; never public downloads or economic replays."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adaptive_replay import intraday_audit as audit
from adaptive_replay.intraday_references import EntryRequest
from adaptive_replay.runner import digest

PLAN = Path(__file__).parents[1] / "intraday-source-plan.json"
URL = audit.PUBLIC_ROOT + "/BTCUSDT/BTCUSDT-aggTrades-2022-05-09.zip"
START = int(datetime(2022, 5, 9, tzinfo=UTC).timestamp() * 1000)


class Response(io.BytesIO):
    def __init__(self, body: bytes, url: str = URL, declared: str | None = None):
        super().__init__(body)
        self.status = 200
        self.url = url
        self.headers = {} if declared is None else {"Content-Length": declared}

    def geturl(self):
        return self.url


def fake_http(monkeypatch, body=b"fixture", *, declared=None, url=URL):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            return Response(body, url, declared)

    monkeypatch.setattr(audit.urllib.request, "build_opener", lambda *handlers: Opener())
    return calls


def test_plan_requires_sealed_byte_identity_and_preserves_no_authority(tmp_path):
    plan = audit.load_source_plan(PLAN)
    assert len(plan["candidate_ids"]) == 12
    assert sum(t["slots"] for t in plan["tapes"]) == 17_280
    assert len(plan["archives"]) == 9
    assert plan["no_economics"] is plan["no_strategy_generation"] is True
    assert plan["readiness"]["STRATEGY_POLICY"] == "REJECT_ALL"
    changed = tmp_path / "plan.json"
    changed.write_bytes(PLAN.read_bytes() + b" ")
    with pytest.raises(ValueError, match="sealed"):
        audit.load_source_plan(changed)


def test_public_get_is_one_bounded_create_only_call(monkeypatch, tmp_path):
    calls = fake_http(monkeypatch, b"recorded", declared="8")
    target = tmp_path / "sample.zip"
    receipt = audit.fetch_public_file(URL, target, 8, time.monotonic() + 30)
    assert receipt["sha256"] == hashlib.sha256(b"recorded").hexdigest()
    assert target.read_bytes() == b"recorded"
    assert receipt["requests"] == 1 and receipt["redirects"] == 0
    assert len(calls) == 1 and 0 < calls[0][1] <= 20
    with pytest.raises(FileExistsError):
        audit.fetch_public_file(URL, target, 8, time.monotonic() + 30)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url", ["http://data.binance.vision/a", URL + "?key=a", URL + "#a", audit.PUBLIC_ROOT + "/../a"]
)
def test_nonfixed_public_destinations_rejected_before_http(monkeypatch, tmp_path, url):
    calls = fake_http(monkeypatch)
    with pytest.raises(ValueError):
        audit.fetch_public_file(url, tmp_path / "sample.zip", 10, time.monotonic() + 30)
    assert not calls


def test_redirect_handler_cannot_follow(monkeypatch, tmp_path):
    handler = audit._NoRedirect()
    assert handler.redirect_request(None, None, 302, None, None, "https://elsewhere.test") is None
    fake_http(monkeypatch, b"ok", url="https://elsewhere.test")
    with pytest.raises(ValueError, match="exact fixed URL"):
        audit.fetch_public_file(URL, tmp_path / "sample.zip", 10, time.monotonic() + 30)


@pytest.mark.parametrize(
    "body,declared", [(b"exceeds", "7"), (b"exceeds", None), (b"x", "2"), (b"x", "invalid")]
)
def test_public_fetch_stream_header_and_truncation_guards(monkeypatch, tmp_path, body, declared):
    calls = fake_http(monkeypatch, body, declared=declared)
    with pytest.raises(ValueError):
        audit.fetch_public_file(URL, tmp_path / "sample.zip", 3, time.monotonic() + 30)
    assert len(calls) == 1


def test_expired_public_fetch_does_not_start_http(monkeypatch, tmp_path):
    calls = fake_http(monkeypatch)
    with pytest.raises(TimeoutError):
        audit.fetch_public_file(URL, tmp_path / "sample.zip", 10, 0)
    assert not calls


def runner_fixture(monkeypatch, tmp_path, *, tamper=""):
    directory = tmp_path / "workspace" / "kairos" / "development" / "adaptive_replay"
    directory.mkdir(parents=True)
    runtime = tmp_path / "workspace" / "runtime"
    runtime.mkdir()
    native = runtime / "native-fixture"
    native.mkdir()
    plan = json.loads(PLAN.read_text())
    request = EntryRequest(
        "BTCUSDT", "fixture-only", START + 9_999, START + 10_000, START + 69_999, START + 10_099, 0
    )
    base = {"fixture": "SYNTHETIC_NOT_NATIVE_MARKET_EVIDENCE"}
    plan["original_plan_sha256"] = digest(base)
    plan["archives"] = [{"symbol": "BTCUSDT", "day": "2022-05-09"}]
    plan["candidate_ids"] = [request.intent_id]
    plan_path = directory / "intraday-source-plan.json"
    plan_path.write_text(json.dumps(plan))
    base_path = directory / "plan.json"
    base_path.write_text(json.dumps(base))
    monkeypatch.setattr(audit, "load_source_plan", lambda path: plan)
    monkeypatch.setattr(audit, "load_plan", lambda path: base)
    monkeypatch.setattr(audit, "source_receipt", lambda *args: {"synthetic_fixture": True})
    monkeypatch.setattr(audit.shutil, "disk_usage", lambda path: type("Space", (), {"free": 2**40})())
    native_calls = []

    def requests(*args):
        native_calls.append(True)
        if len(native_calls) == 2 and tamper == "original-plan":
            base_path.write_text(json.dumps(base) + " ")
        return [request], [{"slots": 1, "synthetic_fixture": True}]

    monkeypatch.setattr(audit, "original_requests", requests)
    content = (
        f"1,10,1,1,1,{request.arrival_ts_ms - 1},false\n"
        f"2,10,1,2,2,{request.arrival_ts_ms + 1},false\n"
        f"3,10,1,3,3,{request.expires_ts_ms + 1},false\n"
    )
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("BTCUSDT-aggTrades-2022-05-09.csv", content)
        zip_body = buffer.getvalue()
    checksum_body = (hashlib.sha256(zip_body).hexdigest() + "  BTCUSDT-aggTrades-2022-05-09.zip\n").encode()

    def fetch(url, target, maximum, deadline):
        body = checksum_body if target.suffix == ".CHECKSUM" else zip_body
        target.write_bytes(body)
        receipt = {
            "filename": target.name,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "url": url,
            "synthetic_fixture": True,
        }
        if tamper == "get-witness" and target.suffix == ".zip":
            receipt["sha256"] = "0" * 64
        return receipt

    monkeypatch.setattr(audit, "fetch_public_file", fetch)
    if tamper == "late-download":
        original_verify = audit.verify_downloads

        def verify(output, downloads, deadline):
            path = output / "BTCUSDT" / downloads[0]["filename"]
            path.write_bytes(path.read_bytes() + b" ")
            original_verify(output, downloads, deadline)

        monkeypatch.setattr(audit, "verify_downloads", verify)
    return plan_path, native, runtime / "one-source-attempt"


def test_synthetic_runner_completes_without_any_economic_or_fill_credit(monkeypatch, tmp_path):
    plan, native, output = runner_fixture(monkeypatch, tmp_path)
    assert audit.run(plan, native, output) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["state"] == "COMPLETED"
    assert result["reference_statuses"] == {"RECORDED_PRINT_REFERENCE": 1}
    assert result["strategy_winner"] is None
    assert result["selection_credit"] is result["economics_computed"] is False
    assert result["quote_observed"] is result["fill_qualified"] is result["capacity_qualified"] is False
    assert result["source_before_after_equal"] is result["downloaded_sources_finally_equal"] is True


@pytest.mark.parametrize("tamper", ["get-witness", "late-download", "original-plan"])
def test_synthetic_runner_source_substitution_fails_closed_and_preserves_attempt(
    monkeypatch, tmp_path, tamper
):
    plan, native, output = runner_fixture(monkeypatch, tmp_path, tamper=tamper)
    assert audit.run(plan, native, output) == 1
    assert not (output / "result.json").exists()
    failure = json.loads((output / "failure.json").read_text())
    assert failure["state"] == "FAILED_CLOSED"
    assert failure["source_prerequisite_resolved"] is failure["economics_computed"] is False
    assert failure["no_automatic_retry"] is True
    assert (output / "before.json").is_file()


def test_source_runner_cannot_write_into_source_or_any_existing_attempt(monkeypatch, tmp_path):
    plan, native, output = runner_fixture(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="disjoint"):
        audit.run(plan, native, native / "child")
    with pytest.raises(ValueError, match="direct child"):
        audit.run(plan, native, plan.parent.parent / "unrelated-output")
    output.mkdir()
    with pytest.raises(ValueError, match="fresh"):
        audit.run(plan, native, output)
