from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from adaptive_replay import historical_context_capture as capture


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "kairos-workspace"
    runtime = workspace / "runtime"
    runtime.mkdir(parents=True)
    repo = workspace / "kairos"
    adaptive = repo / "development" / "adaptive_replay"
    adaptive.mkdir(parents=True)
    (repo / ".git").mkdir()
    (adaptive / "historical-episodes-draft.json").write_text(
        '{"schema":"kairos.development.historical-episode-roster.v1","episodes":'
        '[{"id":"episode_a","candidate_start_utc":"2021-05-17T00:00:00Z",'
        '"candidate_end_exclusive_utc":"2021-05-22T00:00:00Z"}]}',
        encoding="utf-8",
    )
    loader = workspace / "kairos-backtest" / "kairos_backtest" / "data.py"
    loader.parent.mkdir(parents=True)
    loader.write_text("# workspace layout sentinel\n", encoding="utf-8")
    return workspace


def _safe_fetch(calls: list[str], *, fail_at: int | None = None):
    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        assert 0 < byte_limit <= capture.MAX_BODY_BYTES
        assert 0 < timeout <= capture.TIMEOUT_SECONDS
        assert total_remaining > 0
        if fail_at == len(calls):
            raise OSError("synthetic offline failure")
        return f"synthetic body for call {len(calls)}".encode()

    return fetch


def test_all_fixed_leads_are_hashed_with_modern_capture_time_but_never_admitted(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "capture"
    calls: list[str] = []
    times = iter(
        (
            1_000,
            1_001,
            1_010,
            1_011,
            1_020,
            1_021,
            1_030,
            1_031,
            1_040,
            1_041,
            1_050,
            1_051,
            1_060,
            1_061,
            1_070,
            1_071,
            1_080,
            1_081,
        )
    )
    result = capture.capture_public_leads(
        output,
        workspace_root=workspace,
        fetch=_safe_fetch(calls),
        clock=lambda: 0.0,
        wall_ms=lambda: next(times),
    )

    assert calls == [url for _record_id, _scope, url in capture.TARGETS]
    assert len(calls) == 9 == result["requests"]
    assert result["automatic_retries"] == 0
    assert result["state"] == "CAPTURE_COMPLETED_NO_SOURCE_ADMISSION"
    assert result["required_sources_ready"] is False
    assert result["coverage"] == "UNKNOWN"
    assert result["provider_calls"] == 0
    assert result["strategy_generation_executed"] is False
    assert result["economics_executed"] is False
    assert result["trading_authority"] is False
    assert len(result["records"]) == 9
    target_records = zip(capture.TARGETS, result["records"], strict=True)
    for index, ((record_id, scope, url), record) in enumerate(target_records):
        expected = f"synthetic body for call {index + 1}".encode()
        assert (record["id"], record["scope"], record["url"]) == (record_id, scope, url)
        assert record["actual_capture_requested_ms"] is not None
        assert record["actual_captured_ms"] is not None
        assert record["actual_captured_ms"] >= record["actual_capture_requested_ms"]
        assert record["historical_availability_ms"] is None
        assert record["historical_local_receipt_ms"] is None
        assert record["coverage"] == "UNKNOWN"
        assert record["admitted_to_prompt"] is False
        assert record["state"] == "RAW_CAPTURED_UNADMITTED"
        assert record["body_bytes"] == len(expected)
        assert record["raw_sha256"] == hashlib.sha256(expected).hexdigest()
        assert (output / record["filename"]).read_bytes() == expected
        receipt = json.loads((output / f"{record_id}.receipt.json").read_text(encoding="utf-8"))
        assert receipt == record
    assert json.loads((output / "capture-summary.json").read_text(encoding="utf-8")) == result


def test_one_failed_fetch_keeps_other_raws_and_failure_is_not_absence_proof(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "partial"
    calls: list[str] = []
    result = capture.capture_public_leads(
        output,
        workspace_root=workspace,
        fetch=_safe_fetch(calls, fail_at=5),
        clock=lambda: 0.0,
        wall_ms=lambda: 10_000,
    )

    assert len(calls) == 9
    assert len(result["records"]) == 9
    failed = result["records"][4]
    assert failed["state"] == "CAPTURE_FAILED_NO_ABSENCE_PROOF"
    assert failed["error_type"] == "OSError"
    assert failed["coverage"] == "UNKNOWN"
    assert failed["admitted_to_prompt"] is False
    assert failed["historical_availability_ms"] is None
    assert failed["historical_local_receipt_ms"] is None
    assert not (output / f"{failed['id']}.raw").exists()
    for record in (*result["records"][:4], *result["records"][5:]):
        assert (output / record["filename"]).is_file()
    assert result["required_sources_ready"] is False
    assert (output / "capture-summary.json").is_file()


@pytest.mark.parametrize("payload_kind", ["empty", "oversized"])
def test_empty_or_oversized_payload_is_failed_closed_without_raw_admission(
    tmp_path: Path, payload_kind: str
) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "invalid-payload"
    calls: list[str] = []

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        return b"" if payload_kind == "empty" else b"x" * (capture.MAX_BODY_BYTES + 1)

    result = capture.capture_public_leads(
        output, workspace_root=workspace, fetch=fetch, clock=lambda: 0.0, wall_ms=lambda: 20_000
    )
    first = result["records"][0]
    assert len(calls) == 9
    assert first["state"] == "CAPTURE_FAILED_NO_ABSENCE_PROOF"
    assert first["error_type"] == "ValueError"
    assert first["coverage"] == "UNKNOWN"
    assert first["admitted_to_prompt"] is False
    assert not (output / f"{first['id']}.raw").exists()
    assert json.loads((output / f"{first['id']}.receipt.json").read_text(encoding="utf-8")) == first
    assert result["required_sources_ready"] is False


def test_output_collision_preserves_existing_content_and_does_not_fetch(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    calls: list[str] = []
    with pytest.raises(FileExistsError):
        capture.capture_public_leads(output, workspace_root=workspace, fetch=_safe_fetch(calls))
    assert calls == []
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_deadline_after_first_receipt_retains_raw_and_emits_no_summary(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "deadline"
    calls: list[str] = []
    clock_values = iter((0.0, 0.0, 0.0, capture.DEADLINE_SECONDS))

    with pytest.raises(TimeoutError, match="deadline"):
        capture.capture_public_leads(
            output,
            workspace_root=workspace,
            fetch=_safe_fetch(calls),
            clock=lambda: next(clock_values),
            wall_ms=lambda: 30_000,
        )
    assert len(calls) == 1
    first_id = capture.TARGETS[0][0]
    assert (output / f"{first_id}.raw").is_file()
    assert (output / f"{first_id}.receipt.json").is_file()
    assert not (output / "capture-summary.json").exists()


def test_without_capture_flag_cli_performs_no_io_and_no_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "not-created"

    def forbidden(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("capture path must not be called without --capture")

    monkeypatch.setattr(capture, "capture_public_leads", forbidden)
    result = capture.main(["--workspace-root", str(workspace), "--output-root", str(output)])
    assert result == 0
    assert not output.exists()
    assert json.loads(capsys.readouterr().out) == {"network": False, "state": "CAPTURE_NOT_REQUESTED"}


def test_fixed_target_allowlist_and_audit_scopes_are_exact() -> None:
    assert len(capture.TARGETS) == 9
    assert len({record_id for record_id, _scope, _url in capture.TARGETS}) == 9
    assert len({url for _record_id, _scope, url in capture.TARGETS}) == 9
    assert [scope for _record_id, scope, _url in capture.TARGETS] == [
        "UNADMITTED_RELEASE",
        "UNADMITTED_RELEASE",
        "UNADMITTED_RELEASE",
        "UNADMITTED_RELEASE",
        "PUBLICATION_ONLY_LEAD",
        "UNADMITTED_VERSION_ATTESTATION_LEAD",
        "MODERN_DELETION_WITNESS_ONLY",
        "FUTURE_AT_JAN9_CUTS_AUDIT_ONLY",
        "FUTURE_AT_JAN9_CUTS_AUDIT_ONLY",
    ]
    assert all(url.startswith("https://") for _record_id, _scope, url in capture.TARGETS)
    assert [url.rsplit("/", 1)[-1] for _record_id, _scope, url in capture.TARGETS[:4]] == [
        "cpi_04132021.htm",
        "cpi_05122021.htm",
        "cpi_12122023.htm",
        "cpi_01112024.htm",
    ]


def test_last_fetch_crossing_deadline_retains_failure_receipt_without_completed_summary(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    output = workspace / "runtime" / "last-target-deadline"
    elapsed = 0.0
    calls = 0

    def fetch(*_args: object) -> bytes:
        nonlocal elapsed, calls
        calls += 1
        if calls == len(capture.TARGETS):
            elapsed = capture.DEADLINE_SECONDS
        return b"synthetic body"

    with pytest.raises(TimeoutError):
        capture.capture_public_leads(
            output, workspace_root=workspace, fetch=fetch, clock=lambda: elapsed, wall_ms=lambda: 40_000
        )
    assert calls == len(capture.TARGETS)
    assert len(list(output.glob("*.receipt.json"))) == len(capture.TARGETS)
    assert len(list(output.glob("*.raw"))) == len(capture.TARGETS) - 1
    assert not (output / "capture-summary.json").exists()


def test_public_fetch_accepts_only_exact_allowlisted_200_and_retains_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = capture.TARGETS[0][2]
    requested: list[Request] = []
    read_sizes: list[int] = []

    class Response:
        headers = {"Content-Length": "4", "Content-Type": "text/html; charset=utf-8"}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return url

        def read1(self, size: int) -> bytes:
            read_sizes.append(size)
            return b"body"

    class Opener:
        def open(self, request: Request, timeout: float) -> Response:
            requested.append(request)
            assert timeout == 3.0
            return Response()

    handlers: list[object] = []
    monkeypatch.setattr(capture, "build_opener", lambda *items: handlers.extend(items) or Opener())
    response = capture._fetch_public(url, 100, 3.0, 50)

    assert response == capture.CapturedResponse(b"body", 200, "text/html; charset=utf-8")
    assert len(requested) == 1
    assert requested[0].full_url == url
    assert handlers and isinstance(handlers[0], capture._NoRedirect)
    assert read_sizes == [50]


@pytest.mark.parametrize("failure", ["status", "final_url", "length_mismatch", "uncertain_cap"])
def test_public_fetch_rejects_invalid_status_location_or_bounded_body(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    url = capture.TARGETS[0][2]
    opens: list[str] = []
    read_sizes: list[int] = []
    cap = 10 if failure == "uncertain_cap" else 100

    class Response:
        headers = (
            {"Content-Type": "text/html"}
            if failure == "uncertain_cap"
            else {"Content-Length": "4", "Content-Type": "text/html"}
        )

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def getcode(self) -> int:
            return 206 if failure == "status" else 200

        def geturl(self) -> str:
            return "https://evil.example/final" if failure == "final_url" else url

        def read1(self, size: int) -> bytes:
            read_sizes.append(size)
            if len(read_sizes) > 1:
                return b""
            return b"x" * size if failure == "uncertain_cap" else b"abc"

    class Opener:
        def open(self, request: Request, timeout: float) -> Response:
            opens.append(request.full_url)
            return Response()

    monkeypatch.setattr(capture, "build_opener", lambda *_items: Opener())
    with pytest.raises(ValueError):
        capture._fetch_public(url, cap, 2.0, cap)
    assert opens == [url]
    assert read_sizes == (
        []
        if failure in {"status", "final_url"}
        else [cap, cap - 3]
        if failure == "length_mismatch"
        else [cap]
    )


def test_public_fetch_rejects_nonallowlisted_url_before_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("opener must not be created for an unapproved URL")

    monkeypatch.setattr(capture, "build_opener", forbidden)
    with pytest.raises(ValueError, match="allowlist"):
        capture._fetch_public("https://example.test/not-allowed", 10, 1.0, 10)


def test_public_fetch_rejects_redirect_without_following(monkeypatch: pytest.MonkeyPatch) -> None:
    url = capture.TARGETS[0][2]
    opened: list[str] = []
    errors: list[HTTPError] = []

    class TrackedHTTPError(HTTPError):
        close_called = False

        def close(self) -> None:
            self.close_called = True
            super().close()

    class RedirectingOpener:
        def open(self, request: Request, timeout: float) -> object:
            opened.append(request.full_url)
            error = TrackedHTTPError(request.full_url, 302, "redirect", {}, io.BytesIO())
            errors.append(error)
            raise error

    handlers: list[object] = []
    monkeypatch.setattr(capture, "build_opener", lambda *items: handlers.extend(items) or RedirectingOpener())
    try:
        with pytest.raises(ValueError, match="HTTP failed"):
            capture._fetch_public(url, 100, 2.0, 100)
        assert errors[0].close_called and errors[0].fp.closed
    finally:
        for error in errors:
            if not error.close_called:
                error.close()
    assert opened == [url]
    assert len(handlers) == 1 and isinstance(handlers[0], capture._NoRedirect)


def test_capture_rejects_non_200_metadata_and_backwards_capture_clock(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    bad_status_output = workspace / "runtime" / "bad-status"
    bad_status = capture.capture_public_leads(
        bad_status_output,
        workspace_root=workspace,
        fetch=lambda *_args: capture.CapturedResponse(b"body", 206, "text/html"),
        clock=lambda: 0.0,
        wall_ms=lambda: 40_000,
    )
    first = bad_status["records"][0]
    assert first["state"] == "CAPTURE_FAILED_NO_ABSENCE_PROOF"
    assert first["error_type"] == "ValueError"
    assert first["coverage"] == "UNKNOWN"
    assert first["admitted_to_prompt"] is False
    assert not (bad_status_output / f"{first['id']}.raw").exists()

    backwards_output = workspace / "runtime" / "backwards-clock"
    wall_calls = 0

    def backwards_wall_ms() -> int:
        nonlocal wall_calls
        wall_calls += 1
        return 50_000 if wall_calls == 1 else 49_999

    backwards = capture.capture_public_leads(
        backwards_output,
        workspace_root=workspace,
        fetch=lambda *_args: capture.CapturedResponse(b"body", 200, "text/html"),
        clock=lambda: 0.0,
        wall_ms=backwards_wall_ms,
    )
    first = backwards["records"][0]
    assert first["state"] == "CAPTURE_FAILED_NO_ABSENCE_PROOF"
    assert first["error_type"] == "ValueError"
    assert first["coverage"] == "UNKNOWN"
    assert first["admitted_to_prompt"] is False
    assert not (backwards_output / f"{first['id']}.raw").exists()
