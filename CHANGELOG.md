# Changelog

All notable changes to this project are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

No version bump yet. Docs and build-target polish after 1.1.1.

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

[Unreleased]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Rinnegan27/galatiq-invoice-system/releases/tag/v1.1.0
