#!/usr/bin/env python3
"""One-page quality summary for Meta VP review."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def main() -> int:
    from invoice_automation import __version__

    print(f"galatiq-invoice-system version: {__version__}")
    print(f"core/ absent: {not (ROOT / 'core').exists()}")
    print(f"uv.lock present: {(ROOT / 'uv.lock').is_file()}")
    print()

    code_ruff, out_ruff = _run([sys.executable, "-m", "ruff", "check", "."])
    print(f"ruff check: {'PASS' if code_ruff == 0 else 'FAIL'} (exit {code_ruff})")
    if code_ruff != 0 and out_ruff:
        print(out_ruff.splitlines()[0][:200])

    code_fmt, _ = _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    print(f"ruff format: {'PASS' if code_fmt == 0 else 'FAIL'} (exit {code_fmt})")

    markers = ("smoke", "black_box", "white_box")
    print()
    print("pytest marker counts (collected):")
    for marker in markers:
        code, out = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-m",
                marker,
            ]
        )
        total = 0
        for ln in out.splitlines():
            text = ln.strip()
            if ": " in text and text.rsplit(": ", 1)[-1].isdigit():
                total += int(text.rsplit(": ", 1)[-1])
            if "selected" in text or "tests collected" in text:
                summary = text
                break
        else:
            summary = f"{total} tests"
        print(f"  {marker}: {summary} (collect exit {code})")

    print()
    overall = 0 if code_ruff == 0 and code_fmt == 0 else 1
    print(f"quality_report: {'READY' if overall == 0 else 'NEEDS FIX'}")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
