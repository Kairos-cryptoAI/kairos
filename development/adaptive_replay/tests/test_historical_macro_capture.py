from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest

from adaptive_replay import historical_macro_capture as macro


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "runtime").mkdir(parents=True)
    (workspace / "kairos" / ".git").mkdir(parents=True)
    draft = workspace / "kairos" / "development" / "adaptive_replay" / "historical-episodes-draft.json"
    draft.parent.mkdir(parents=True)
    draft.write_text(
        '{"schema":"kairos.development.historical-episode-roster.v1","episodes":'
        '[{"id":"episode_a","candidate_start_utc":"2021-05-17T00:00:00Z",'
        '"candidate_end_exclusive_utc":"2021-05-22T00:00:00Z"}]}',
        encoding="utf-8",
    )
    loader = workspace / "kairos-backtest" / "kairos_backtest" / "data.py"
    loader.parent.mkdir(parents=True)
    loader.write_text("# layout sentinel", encoding="utf-8")
    return workspace


def _zip(members: tuple[tuple[str, bytes], ...] = (("README.txt", b"fixture"),)) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return stream.getvalue()


def test_single_download_retains_raw_bytes_but_never_admits_them(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    root = workspace / "runtime" / "macro"
    payload = _zip((("README.txt", b"2021-05-18 2024-01-08 fixture"), ("CPIAUCSL.csv", b"fixture")))
    calls = []
    clocks = iter((100, 101))

    def fetch() -> macro.Response:
        calls.append("public-download")
        return macro.Response(payload, 200, "application/zip")

    result = macro.capture(root, workspace_root=workspace, fetch=fetch, wall_ms=lambda: next(clocks))
    assert calls == ["public-download"]
    assert result["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (root / result["raw_file"]).read_bytes() == payload
    assert result["state"] == "RAW_VINTAGE_DOWNLOAD_CAPTURED_UNADMITTED"
    assert result["actual_captured_ms"] == 101
    assert result["coverage"] == "UNKNOWN"
    assert result["admitted_to_prompt"] is False
    assert result["historical_receive_clock_proven"] is False
    assert result["provider_calls"] == 0
    assert result["economics_executed"] is False
    assert result["trading_authority"] is False
    assert result["automatic_retries"] == 0
    assert json.loads((root / "receipt.json").read_bytes()) == result
    with pytest.raises(FileExistsError):
        macro.capture(root, workspace_root=workspace, fetch=fetch)
    assert calls == ["public-download"]


def test_html_failure_is_retained_without_retry_or_absence_claim(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    root = workspace / "runtime" / "macro"
    result = macro.capture(
        root,
        workspace_root=workspace,
        fetch=lambda: macro.Response(b"<html>not a vintage</html>", 200, "text/html"),
    )
    assert result["state"] == "MACRO_CAPTURE_BLOCKED_NO_ABSENCE_PROOF"
    assert result["error_type"] == "BadZipFile"
    assert (root / result["raw_file"]).is_file()
    assert result["coverage"] == "UNKNOWN"


def test_transport_failure_is_sanitized_and_never_retried(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    calls = []

    def fetch() -> macro.Response:
        calls.append(1)
        raise OSError("untrusted server exception text")

    result = macro.capture(workspace / "runtime" / "macro", workspace_root=workspace, fetch=fetch)
    assert calls == [1]
    assert result["error_type"] == "OSError"
    assert "untrusted" not in json.dumps(result)
    assert result["raw_file"] is None


@pytest.mark.parametrize("name", ["../CPI.csv", "x/CPI.csv", "x\\CPI.csv", "C:CPI.csv", "CPI.exe"])
def test_zip_member_names_are_bounded_no_extract(name: str) -> None:
    with pytest.raises(ValueError):
        macro.inspect_zip(_zip(((name, b"fixture"),)))


def test_zip_members_are_unique_and_bounded() -> None:
    with pytest.warns(UserWarning), pytest.raises(ValueError):
        macro.inspect_zip(_zip((("CPI.csv", b"a"), ("CPI.csv", b"b"))))
    with pytest.raises(ValueError):
        macro.inspect_zip(_zip(tuple((f"CPI{i}.csv", b"a") for i in range(9))))
    with pytest.raises(ValueError):
        macro.inspect_zip(b"x" * (macro.BODY_LIMIT + 1))


class _HTTPResponse:
    def __init__(self, payload: bytes, *, length: str | None = None, status: int = 200) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/zip"}
        if length is not None:
            self.headers["Content-Length"] = length
        self.stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()

    def read1(self, amount: int) -> bytes:
        return self.stream.read(amount)

    def geturl(self) -> str:
        return macro.URL


def _opener(monkeypatch, response: _HTTPResponse, requests: list) -> None:
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 20.0
            return response

    monkeypatch.setattr(macro.urllib.request, "build_opener", lambda handler: Opener())


def test_transport_uses_observed_public_form_one_post_no_api_key(monkeypatch) -> None:
    payload = _zip()
    requests = []
    _opener(monkeypatch, _HTTPResponse(payload, length=str(len(payload))), requests)
    result = macro._fetch(clock=lambda: 0.0)
    assert result.body == payload
    assert len(requests) == 1
    assert requests[0].full_url == macro.URL
    assert requests[0].method == "POST"
    assert parse_qs(requests[0].data.decode(), keep_blank_values=True) == {
        key: [value] for key, value in macro.FIELDS.items()
    }


@pytest.mark.parametrize("length,status", [("1048577", 200), ("x", 200), ("2", 200), (None, 403)])
def test_transport_rejects_bad_headers_status_or_truncation(monkeypatch, length, status) -> None:
    _opener(monkeypatch, _HTTPResponse(b"a", length=length, status=status), [])
    with pytest.raises(ValueError):
        macro._fetch(clock=lambda: 0.0)


def test_transport_body_and_final_deadline_checks(monkeypatch) -> None:
    _opener(monkeypatch, _HTTPResponse(b"a" * (macro.BODY_LIMIT + 1)), [])
    with pytest.raises(ValueError):
        macro._fetch(clock=lambda: 0.0)
    _opener(monkeypatch, _HTTPResponse(b"a"), [])
    clock = iter((0.0, 0.0, 20.0))
    with pytest.raises(TimeoutError):
        macro._fetch(clock=lambda: next(clock))


def test_transport_rejects_response_url_mismatch(monkeypatch) -> None:
    response = _HTTPResponse(b"a")
    monkeypatch.setattr(response, "geturl", lambda: "https://other.invalid/")
    _opener(monkeypatch, response, [])
    with pytest.raises(ValueError):
        macro._fetch(clock=lambda: 0.0)


def test_redirects_are_rejected() -> None:
    request = macro.urllib.request.Request(macro.URL)
    with pytest.raises(ValueError):
        macro._NoRedirect().redirect_request(request, None, 302, "found", {}, "https://other.invalid")


def test_default_cli_never_requests_or_creates_output(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    root = workspace / "runtime" / "macro"

    def reject(*args, **kwargs):
        raise HTTPError(macro.URL, 500, "must never be called", {}, None)

    monkeypatch.setattr(macro, "capture", reject)
    assert macro.main(["--workspace-root", str(workspace), "--output-root", str(root)]) == 0
    assert not root.exists()
