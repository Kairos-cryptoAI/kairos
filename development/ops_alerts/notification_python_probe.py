"""One-shot Limited task interpreter probe; no credentials or runtime imports."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

RESULT = Path(
    "D:/Kairos/runtime/alert-delivery-20261012/operational-r4/python-host-probe-v2.json"
)
TARGETS = {
    "venv_home": Path(
        "C:/Users/loval/AppData/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe"
    ),
    "physical_base": Path(
        "C:/Users/loval/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe"
    ),
    "persistence_launcher": Path(
        "D:/Kairos/kairos-persistence/.venv/Scripts/python.exe"
    ),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "--execute":
        print('{"status":"PLAN_ONLY"}')
        return 0
    checks = {}
    for name, target in TARGETS.items():
        present = target.is_file()
        code, version = None, None
        if present:
            try:
                call = subprocess.run(
                    [str(target), "-B", "-E", "-s", "--version"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                code = call.returncode
                if code == 0 and re.fullmatch(
                    rb"Python [0-9]+\.[0-9]+\.[0-9]+\r?\n?", call.stdout
                ):
                    version = call.stdout.decode("ascii").strip()
            except (OSError, subprocess.SubprocessError):
                code = "PROBE_BLOCKED"
        checks[name] = {"present": present, "exit_code": code, "version": version}
    for path in (RESULT.parent, *RESULT.parent.parents):
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            return 2
    report = {
        "kind": "kairos.notifications.limited-python-host-probe.v2",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "checks": checks,
        "credential_reads": 0,
        "network_calls": 0,
        "trading_authority": False,
    }
    descriptor = os.open(
        RESULT, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_BINARY, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            return 2
        stream.write(json.dumps(report, sort_keys=True).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
