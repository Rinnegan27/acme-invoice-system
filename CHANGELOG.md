# Changelog

All notable changes to this project are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Mock OIDC IdP + HMAC-signed workbench sessions (`/login`, `galatiq_session` cookie).
- Unit-price catalog + optional PO coverage checks; stock decrement after successful pay.
- OpenTelemetry-shaped stage spans in `spans.jsonl` (optional `opentelemetry-api`).
- HV fraud eval fixtures under `data/evals/hv_fraud/` + stub eval tests.
- Pinned Grok prompt versions (`extract-v1` / `approve-v1`); tighter Grok circuit breaker.

### Changed

- Inventory availability sums quantities by SKU (INV-1013 multi-line oversell → `insufficient_stock`).
- Case contract: W6b expects reject on 1013; W6a/W6a2 use in-stock HV `invoice_1160.txt`.

### Notes

- Custom orchestration stays. No LangChain / LangGraph migration.
- Unit-price / PO checks are opt-in (`require_price_check` / `require_po`); catalog tables are seeded.
- Roadmap: live OIDC tenant, OTLP export, mandatory PO matching.

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
