# Changelog

All notable changes to this project are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.1] — 2026-10-11

### Changed

- Restore NumPy docstrings on post-overhaul public APIs (saga, inventory,
  spans, auth, outbox). Keep short inline comments on private helpers.

## [1.2.0] — 2026-10-11

### Added

- Mock OIDC IdP and HMAC-signed workbench sessions (`/login`, `galatiq_session`).
- Unit-price catalog, soft price bands, and optional PO checks.
- Stock decrement after a successful pay.
- Stage spans in `spans.jsonl` and local OTLP/JSON batch `otlp_traces.json`.
- HV fraud eval fixtures under `data/evals/hv_fraud/` plus stub eval tests.
- Optional live HV smoke (`pytest -m live_grok`).
- Pinned Grok prompt versions (`extract-v1` / `approve-v1`).
- Pay/stock reconcile: gateway success and stock fail set `RECONCILE` and emit
  `PaymentStockReconcile`.

### Changed

- CLI and pipeline summaries prefer extracted `INV-…` ids over file stems.
- Inventory sums quantity by SKU (INV-1013 multi-line oversell fails).
- Case contract: W6b rejects 1013; W6a/W6a2 use in-stock HV `invoice_1160.txt`.
- Invariants allow totals above priced lines for tax or fees.

### Notes

- Custom orchestration stays. No LangChain or LangGraph migration.
- Soft price bands are on by default. Strict catalog and PO checks stay opt-in.
- Roadmap: live OIDC tenant; mandatory PO matching as a hard default.

## [1.1.1] — 2026-10-11

### Fixed

- Verify `PaymentPermit` before pay. Consume the nonce only after pay succeeds.
- Keep Grok `due_date` values on the invoice model.

### Changed

- Lead the README with How to run (ASD-STE).
- Rename quality persona to **Aether Helix**.
- Default `make` / `make build` runs sync, lint, offline tests, and scenario proof.
- Add evaluator demo path with live Grok first.
- Check in `docs/scenario_proof.*` for the case README invoice matrix.
- Document OpenAI-compatible xAI API (`https://api.x.ai/v1`).
- Sync `uv.lock` with package version 1.1.1.

### Added

- Payment retry tests for consume-after-pay.
- CI offline gates through `make check` and `make scenario-proof`.

## [1.1.0] — 2026-10-11

### Added

- Replace legacy `core/` with package `invoice_automation/`.
- Four-stage durable SQLite queue: Ingestion → Validation → Approval → Payment.
- Case-brief inventory seed and `mock_payment` API.
- Offline stub LLM and live Grok client (OpenAI-compatible xAI API).
- HMAC `PaymentPermit` fence. LLM text cannot authorize pay alone.
- FastAPI AP Control Centre (`web/`) with workbench and Case Lab.
- 100-file multi-format corpus under `data/invoices/`.
- Case Simulation Contract W1–W10 (`--sim=case`).
- `uv.lock`, Makefile, ruff, smoke / black_box / white_box markers.
- GitHub Actions offline CI (optional live Grok job).
- Auto-create blank `GALATIQ_PERMIT_SECRET` on first run.

### Notes

- Product UI is FastAPI. Streamlit `ui/` is deprecated.
- Orchestration is a custom queue pipeline. It is not LangGraph.

[Unreleased]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Rinnegan27/galatiq-invoice-system/releases/tag/v1.1.0
