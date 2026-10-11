#!/usr/bin/env python3
"""Create a local .env with a strong permit secret (never commits secrets).

Usage
-----
python scripts/bootstrap_env.py
# then edit .env and set: XAI_API_KEY=xai-<your-real-key>
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
ENV = ROOT / ".env"


def main() -> int:
    if not EXAMPLE.is_file():
        print(f"error: missing {EXAMPLE}", file=sys.stderr)
        return 1

    secret = secrets.token_hex(32)
    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        if line.startswith("GALATIQ_PERMIT_SECRET="):
            out.append(f"GALATIQ_PERMIT_SECRET={secret}")
        else:
            out.append(line)

    if ENV.exists():
        print(f"{ENV} already exists — not overwriting.")
        print("Set XAI_API_KEY manually, or delete .env and re-run this script.")
        return 0

    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {ENV}")
    print("Next:")
    print("  1. Edit .env and set XAI_API_KEY=xai-<your-real-key>")
    print("  2. Keep XAI_MODEL=grok-3 (or your model)")
    print("  3. Smoke test:")
    print("       python main.py --invoice_path=data/invoices/invoice1.txt")
    print("       pytest -m live_grok -q")
    print("Never commit .env (already in .gitignore).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
