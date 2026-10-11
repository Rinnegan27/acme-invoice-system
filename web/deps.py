"""Shared web dependencies."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from invoice_automation.case_brief import is_live_xai_key
from invoice_automation.sim.corpus import sample_paths as corpus_sample_paths
from invoice_automation.workbench.service import WorkbenchService

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
RUNTIME = ROOT / ".galatiq_runtime" / "control_centre"
DATA_DIR = ROOT / "data" / "invoices"
UPLOAD_DIR = RUNTIME / "uploads"
SIM_DIR = RUNTIME / "sim"
SIM_REPORT_PATH = SIM_DIR / "last_report.json"


@lru_cache(maxsize=2)
def get_service(use_grok: bool = False) -> WorkbenchService:
    return WorkbenchService(RUNTIME / "wb", use_grok=use_grok)


def service_from_cookie(llm: str = "stub") -> WorkbenchService:
    use_grok = llm == "grok" and is_live_xai_key(os.getenv("XAI_API_KEY"))
    return get_service(use_grok)


def sample_paths() -> list[Path]:
    """One file per invoice stem (prefer txt > json > csv > xml > pdf)."""
    return corpus_sample_paths(DATA_DIR)
