# Changelog

All notable changes to this project are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.8.0] — 2026-10-12

### Added

- CLI human-in-the-loop for VP scrutiny: interactive ``a`` / ``r`` / ``e``
  (approve / reject / escalate-to-VP-agent). Default on TTY; ``--auto-vp`` /
  ``GALATIQ_CLI_AUTO_VP=1`` for CI. Emits ``HumanApprovalGate``.
- Live extract guardrails: raw ``Qty`` ``~`` / float fail-closed; undo
  digit-SKU LLM expansions (``Widg3tA``); soft-escalate source aliases
  (``Widget Alpha``); soft ``vendor_injection_review`` for SQL-smuggle
  vendors; Grok prompts ``extract-v6`` / ``approve-v6``.
- Stateful ledger script ``scripts/run_stateful_ledger_live_grok.py`` with
  ``STOCK_MULT``; Makefile ``make ledger`` / ``make ledger-live`` / ``make uat``.

### Changed

- Stage-graph validation edges renamed ``hard_issues`` /
  ``hard_issues_empty`` (soft escalations still route to approval).
- Prod profile defaults high-value Grok approve to deterministic
  (``ApprovalAudit``); override with ``GALATIQ_HV_DETERMINISTIC=0|1``.
- README version badges aligned to package version.

## [1.7.1] — 2026-10-12

### Fixed

- Revision / format-twin stock validation credits quantities already drawn
  by a ``SUCCEEDED`` payment for the same ``invoice_id``. Availability
  checks use ``max(0, new_qty − prior_qty)``, matching payment-saga stock
  deltas (e.g. WidgetA 3→4 only needs +1 on the shelf).

## [1.7.0] — 2026-10-12

### Added

- Generic ``CatalogResolver`` (``policy/sku_resolve.py``): confidence-tier
  matching against the live catalog (exact / unique_close / ambiguous /
  variant / none) — no product-specific alias tables. Short abbreviations
  (compact length ≤ 3) are never auto-mapped to catalog codes; LLM
  over-expansions are undone from the source ``Item:`` text. Soft
  escalations feed VP; live Grok extract/approve prompts carry catalog
  intelligence for the same policy.
- Generic quantity coercion in parsers: English numbers 0–99, scientific
  notation, unit-noise strip; reject fractions, ``~``, and ``%``.
- Inflated-total guard: priced lines vs total beyond ~15% →
  ``amount_line_mismatch`` (UAT ghost-phantom total).
- Offline UAT harness: ``tests/test_uat_scenarios.py`` covers
  ``docs/uat_test_cases.md``. Live runner: ``scripts/run_uat_live_grok.py``.

### Changed

- Spaced catalog labels (``Widget A``) auto-normalize without VP when the
  compact form matches exactly (UAT TC-NAME-01 / INV-1012).
- High-value VP threshold is inclusive (``amount >= 10000``).
- Grok extract prompt ``extract-v5``: do not expand short abbreviations
  into catalog SKUs.

## [1.6.0] — 2026-10-12

### Added

- Soft ``sku_typo_review`` findings when extract maps spaced labels
  (``Widget A`` / ``Gadget X``) to catalog SKUs. Validation escalates to VP
  reflection instead of silent under-$10k auto-pay (INV-1012 path).
- Payment dedupe / revision: same ``invoice_id`` with identical payload
  (e.g. ``1011.txt`` + ``1011.pdf``) replays without a second stock draw;
  changed lines/totals (e.g. ``1004`` → ``1004_revised``) pay the amount
  delta, adjust stock, and store updated ``items_json``.
- Vendor split / structuring detection: under-$10k invoices from the same
  vendor within 5 minutes that cumulate above $10k raise
  ``vendor_split_risk`` and escalate to VP (UAT 2.1).

### Notes

- Catalog unit prices live in ``inventory.db`` tables ``unit_prices`` and
  ``unit_price_bands`` (seeded; used for validation, not invoice history).

## [1.5.0] — 2026-10-11

### Added

- SKU guardrail: strip trailing parenthetical notes
  (``WidgetA (rush order)`` → ``WidgetA``) on ``LineItem`` construct so live
  Grok does not false-reject rush/expedite lines.
- Invoice amount resolution: prefer TOTAL, else SUBTOTAL, else sum of
  priced lines (qty × unit_price). Fail only when amount cannot be computed.
  Deterministic parsers and Grok extract-v3 share the same policy.

### Changed

- Text/JSON/XML/CSV extract no longer fail-closed solely because TOTAL is
  missing when unit prices (or subtotal) are present.

## [1.4.0] — 2026-10-11

### Added

- Explicit orchestration stage graph (``stage_graph.py``) with conditional
  edges and wavefront ``select_ready_stage`` drain.
- Strict graph validation + wavefront / CLI stdout-purity tests.

### Changed

- ``configure_logging`` forces root and httpx/openai loggers onto **stderr**
  (replaces any stdout handlers) so live Grok CLI stdout stays one JSON object.
- ``docs/architecture.md`` matches the coded graph edges.

## [1.3.0] — 2026-10-11

### Added

- ``GALATIQ_PROFILE`` / CLI ``--profile``: **prod** (default) hardens catalog
  price + PO checks; **case** keeps soft bands for the case corpus.
- Control Centre **Reconcile** desk (`/reconcile`): retry stock or ack
  ``PaymentStockReconcile`` intents.
- Optional ``GALATIQ_OTLP_HTTP_ENDPOINT`` best-effort OTLP/JSON POST.
- ``docs/architecture.md`` orchestration diagram + OTel export path.

### Changed

- ``mock_payment`` and span console logs write to **stderr** so CLI/sim
  ``stdout`` is a single JSON document.
- Case sim, scenario-proof, and pytest force the ``case`` profile.

## [1.2.2] — 2026-10-11

### Added

- Normalize bare / stem invoice ids to ``INV-…`` (live Grok + parsers).
- Strict Grok approve JSON schema + deterministic approve guardrails.
- CLI ``--strict-master-data`` for catalog unit-price checks.
- ``GALATIQ_HV_DETERMINISTIC=1`` one-shot HV approve + ``ApprovalAudit`` event.
- Payment saga keys by business ``INV-…`` id; ``source_stem`` is audit metadata.

### Changed

- Narrow worker exception handling; unexpected errors re-raise after queue fail.
- Grok extract prompt ``extract-v2``; approve prompt ``approve-v2``.

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

[Unreleased]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.8.0...HEAD
[1.8.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/Rinnegan27/galatiq-invoice-system/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Rinnegan27/galatiq-invoice-system/releases/tag/v1.1.0
