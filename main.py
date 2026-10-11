#!/usr/bin/env python3
"""Galatiq case CLI entrypoint.

Usage
-----
python main.py --invoice_path=data/invoices/invoice1.txt          # Grok by default (summary JSON)
python main.py --invoice_path=data/invoices/invoice1.txt -v       # full audit JSON
python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub
python main.py --all
python main.py --sim=case --llm=stub
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from invoice_automation.main import main

if __name__ == "__main__":
    raise SystemExit(main())
