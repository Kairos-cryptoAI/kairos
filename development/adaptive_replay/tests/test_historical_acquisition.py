from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from adaptive_replay import historical_acquisition as acquisition
from adaptive_replay.inputs import UNIVERSE

BAR_HEADER = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)
FUNDING_HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")


def _archive(member_name: str, content: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return stream.getvalue()


def _may_archives() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    month_start = datetime(2021, 5, 1, tzinfo=UTC)
    month_minutes = 31 * 24 * 60
    for _symbol, kind, url, relative in acquisition._targets():
        filename = relative.name
        if kind == "bars":
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(BAR_HEADER)
            for minute in range(month_minutes):
                open_ms = int((month_start + timedelta(minutes=minute)).timestamp() * 1_000)
                writer.writerow(
                    (open_ms, "100", "101", "99", "100", "1", open_ms + 59_999, "100", "1", "0.5", "50", "0")
                )
            content = buffer.getvalue().encode("utf-8")
        else:
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(FUNDING_HEADER)
            for hours in range(0, 31 * 24, 8):
                timestamp = int((month_start + timedelta(hours=hours)).timestamp() * 1_000)
                writer.writerow((timestamp, 8, "0.0001"))
            content = buffer.getvalue().encode("utf-8")
        data = _archive(filename[:-4] + ".csv", content)
        sidecar = f"{hashlib.sha256(data).hexdigest()} *{filename}\n".encode("ascii")
        payloads[url] = data
        payloads[f"{url}.CHECKSUM"] = sidecar
    return payloads


@pytest.fixture(scope="module")
def payloads() -> dict[str, bytes]:
    return _may_archives()


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    workspace = tmp_path / "kairos-workspace"
    runtime = workspace / "runtime"
    runtime.mkdir(parents=True)
    roster = workspace / "kairos" / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    roster.parent.mkdir(parents=True)
    roster.write_text(
        '{"schema":"kairos.development.historical-episode-roster.v1","episodes":'
        '[{"id":"episode_a","candidate_start_utc":"2021-05-17T00:00:00Z",'
        '"candidate_end_exclusive_utc":"2021-05-22T00:00:00Z"}]}',
        encoding="utf-8",
    )
    (workspace / "kairos" / ".git").mkdir()
    loader = workspace / "kairos-backtest" / "kairos_backtest" / "data.py"
    loader.parent.mkdir(parents=True)
    loader.write_text("# fixture layout sentinel\n", encoding="utf-8")
    return workspace


@pytest.fixture
def runtime_root(workspace_root: Path) -> Path:
    runtime = workspace_root / "runtime"
    return runtime


def _fake_fetch(payloads: dict[str, bytes], calls: list[str]):
    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        assert timeout <= acquisition.REQUEST_TIMEOUT_SECONDS
        assert total_remaining > 0
        return payloads[url]

    return fetch


def test_success_is_fixed_roster_official_hash_bound_and_source_only(
    runtime_root: Path, workspace_root: Path, payloads: dict[str, bytes]
) -> None:
    calls: list[str] = []
    result = acquisition.acquire_episode_a_may_2021(
        runtime_root / "historical-acquisition-test",
        workspace_root=workspace_root,
        fetch=_fake_fetch(payloads, calls),
    )

    assert len(calls) == acquisition.MAX_REQUESTS == 20
    assert all(url.startswith("https://data.binance.vision/data/futures/um/monthly/") for url in calls)
    assert len(set(calls)) == 20
    assert result["state"] == "SOURCE_INPUTS_VALIDATED_ONLY"
    assert result["provider_calls"] == 0
    assert result["strategy_or_economics_executed"] is False
    assert result["trading_authority"] is False
    assert set(result["source_summary"]) == set(UNIVERSE)
    for summary in result["source_summary"].values():
        assert summary["bars"] == 9 * 1_440
        assert summary["funding"] == 27
        assert summary["gaps"] == 0
        assert len(summary["bar_sha256"]) == len(summary["funding_sha256"]) == 64
    assert len(list((runtime_root / "historical-acquisition-test").rglob("*.zip"))) == 10
    summary_path = runtime_root / "historical-acquisition-test" / "source-summary.json"
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result
    assert result["state"] == "SOURCE_INPUTS_VALIDATED_ONLY"


def test_no_fetch_mode_does_not_create_or_call_network(
    runtime_root: Path, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = runtime_root / "not-created"

    def forbidden(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("network must not be called without --fetch")

    monkeypatch.setattr(acquisition, "_http_fetch", forbidden)
    assert acquisition.main(["--workspace-root", str(workspace_root), "--output-root", str(target)]) == 0
    assert not target.exists()


def test_only_fixed_official_urls_are_accepted() -> None:
    expected = acquisition._targets()[0][2]
    acquisition._validate_target_url(expected, expected)
    for bad in (
        expected.replace("https://", "http://"),
        expected.replace("data.binance.vision", "evil.example"),
        expected + "?token=x",
        expected.replace("https://", "https://user:pass@"),
        expected.replace("2021-05", "2021-06"),
    ):
        with pytest.raises(ValueError):
            acquisition._validate_target_url(bad, expected)


def test_existing_output_root_is_rejected_without_fetch(runtime_root: Path, workspace_root: Path) -> None:
    target = runtime_root / "existing"
    target.mkdir()
    calls: list[str] = []
    with pytest.raises(FileExistsError):
        acquisition.acquire_episode_a_may_2021(
            target,
            workspace_root=workspace_root,
            fetch=lambda *args: calls.append(str(args)) or b"",
        )
    assert calls == []


def test_relative_and_outside_runtime_roots_are_rejected(runtime_root: Path, workspace_root: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        acquisition._validate_output_root(Path("relative-output"), workspace_root)
    outside = runtime_root.parent / "outside"
    with pytest.raises(ValueError, match="runtime"):
        acquisition._validate_output_root(outside, workspace_root)


def test_failure_keeps_only_completed_verified_pairs_and_never_retries(
    runtime_root: Path, workspace_root: Path, payloads: dict[str, bytes]
) -> None:
    root = runtime_root / "partial"
    calls: list[str] = []

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        if len(calls) == 3:
            raise OSError("offline fake failure")
        return payloads[url]

    with pytest.raises(OSError, match="offline fake failure"):
        acquisition.acquire_episode_a_may_2021(root, workspace_root=workspace_root, fetch=fetch)
    assert len(calls) == 3
    first_archive = root / acquisition._targets()[0][3]
    first_checksum = first_archive.with_name(first_archive.name + ".CHECKSUM")
    assert first_archive.is_file() and first_checksum.is_file()
    assert not (root / acquisition._targets()[1][3]).exists()
    assert not list(root.rglob("*acceptance*"))


@pytest.mark.parametrize("failure", ["wrong_hash", "bad_zip", "wrong_member"])
def test_unverified_or_invalid_archive_is_not_retained(
    runtime_root: Path, workspace_root: Path, payloads: dict[str, bytes], failure: str
) -> None:
    root = runtime_root / failure
    first_url = acquisition._targets()[0][2]
    archive = payloads[first_url]
    checksum = payloads[f"{first_url}.CHECKSUM"]
    if failure == "wrong_hash":
        checksum = checksum.replace(hashlib.sha256(archive).hexdigest().encode(), b"0" * 64)
    elif failure == "bad_zip":
        archive = b"not-a-zip"
        checksum = f"{hashlib.sha256(archive).hexdigest()} *{acquisition._targets()[0][3].name}\n".encode()
    else:
        archive = _archive("unexpected.csv", b"x")
        filename = acquisition._targets()[0][3].name
        checksum = f"{hashlib.sha256(archive).hexdigest()} *{filename}\n".encode()
    calls: list[str] = []

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        return archive if url == first_url else checksum

    with pytest.raises(ValueError):
        acquisition.acquire_episode_a_may_2021(root, workspace_root=workspace_root, fetch=fetch)
    assert len(calls) == 2
    assert not (root / acquisition._targets()[0][3]).exists()
    assert not list(root.rglob("*acceptance*"))


@pytest.mark.parametrize("oversize", ["archive", "checksum"])
def test_archive_and_checksum_limits_stop_without_retry(
    runtime_root: Path, workspace_root: Path, payloads: dict[str, bytes], oversize: str
) -> None:
    root = runtime_root / f"oversize-{oversize}"
    calls: list[str] = []
    archive_url = acquisition._targets()[0][2]

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        if oversize == "archive" and url == archive_url:
            return b"x" * (byte_limit + 1)
        if oversize == "checksum" and url == f"{archive_url}.CHECKSUM":
            return b"x" * (byte_limit + 1)
        return payloads[url]

    with pytest.raises(ValueError, match="byte"):
        acquisition.acquire_episode_a_may_2021(root, workspace_root=workspace_root, fetch=fetch)
    assert (
        calls == [archive_url] if oversize == "archive" else calls == [archive_url, f"{archive_url}.CHECKSUM"]
    )
    assert not list(root.rglob("*.zip"))


def test_aggregate_byte_budget_is_enforced(
    runtime_root: Path, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = runtime_root / "total-budget"
    monkeypatch.setattr(acquisition, "MAX_TOTAL_FETCHED_BYTES", 64)
    calls: list[str] = []

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        assert total_remaining == 64
        return b"z" * 65

    with pytest.raises(ValueError, match="total-byte"):
        acquisition.acquire_episode_a_may_2021(root, workspace_root=workspace_root, fetch=fetch)
    assert len(calls) == 1
    assert not list(root.rglob("*.zip"))


def test_deadline_is_shared_and_stops_before_retaining_first_archive(
    runtime_root: Path, workspace_root: Path
) -> None:
    root = runtime_root / "deadline"
    now = [0.0]
    calls: list[str] = []

    def fetch(url: str, byte_limit: int, timeout: float, total_remaining: int) -> bytes:
        calls.append(url)
        now[0] = acquisition.DEADLINE_SECONDS
        return b"x"

    with pytest.raises(TimeoutError, match="deadline"):
        acquisition.acquire_episode_a_may_2021(
            root, workspace_root=workspace_root, fetch=fetch, clock=lambda: now[0]
        )
    assert len(calls) == 1
    assert not list(root.rglob("*.zip"))


def test_http_fetch_refuses_redirect_without_following(monkeypatch: pytest.MonkeyPatch) -> None:
    url = acquisition._targets()[0][2]
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
            error = TrackedHTTPError(url, 302, "redirect", {}, io.BytesIO())
            errors.append(error)
            raise error

    monkeypatch.setattr(acquisition, "build_opener", lambda *_handlers: RedirectingOpener())
    try:
        with pytest.raises(ValueError, match="redirects are disabled"):
            acquisition._http_fetch(url, 128, 2.0, 128)
        assert errors[0].close_called and errors[0].fp.closed
    finally:
        for error in errors:
            if not error.close_called:
                error.close()
    assert opened == [url]


def test_http_fetch_never_reads_past_tightest_byte_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    url = acquisition._targets()[0][2]
    reads: list[int] = []

    class Response:
        headers: dict[str, str] = {}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return url

        def read(self, size: int) -> bytes:
            reads.append(size)
            return b"x" * size

    class Opener:
        def open(self, _request: object, timeout: float) -> Response:
            assert timeout == 1.0
            return Response()

    monkeypatch.setattr(acquisition, "build_opener", lambda *_handlers: Opener())
    with pytest.raises(ValueError, match="uncertain hard byte limit"):
        acquisition._http_fetch(url, 10, 1.0, 4)
    assert reads == [4]
    assert sum(reads) <= 4


def test_zip_member_decompression_limit_is_checked_before_read() -> None:
    payload = _archive("expected.csv", b"x" * (acquisition.MAX_UNCOMPRESSED_BYTES + 1))
    with pytest.raises(ValueError, match="decompressed-byte bound"):
        acquisition._check_archive_zip(payload, "expected.csv")


def test_runtime_output_root_symlink_is_rejected_when_supported(
    runtime_root: Path, workspace_root: Path
) -> None:
    target = runtime_root / "existing-target"
    target.mkdir()
    link = runtime_root / "linked-output"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"platform cannot create test symlink: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        acquisition._validate_output_root(link, workspace_root)
