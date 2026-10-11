# Galatiq Invoice Processing System

Version **1.1.0**. Multi-agent AP automation for the [Galatiq case](https://github.com/galatiq-ai/galatiq-case-invoices).

Acme Corp loses about **$2M/year** on manual invoice work (**30% error rate**, **5-day cycle**). This system runs a controlled AP flow:

**Capture → Exceptions → Approvals → Audit and payments**

The product UI is the **AP Control Centre** in `web/` (FastAPI). The Streamlit app under `ui/` is **deprecated**.

## Quick start

Use **uv** (primary). Keep `uv.lock` committed.

```bash
# Install uv: https://docs.astral.sh/uv/
uv sync --extra dev

# Case CLI (brief path). Default engine is Grok. Summary JSON is the default output.
uv run python main.py --invoice_path=data/invoices/invoice1.txt

# Offline golden (no API key)
uv run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub

# Full audit JSON
uv run python main.py --invoice_path=data/invoices/invoice1.txt -v

# Process all sample invoices
uv run python main.py --all --llm=stub

# Case Simulation Contract (W1–W10)
uv run python main.py --sim=case --llm=stub

# AP Control Centre
uv run uvicorn web.app:app --reload --port 8000
# open http://localhost:8000
# Case Lab (not in product nav): http://localhost:8000/sim
```

Pip fallback (no lockfile guarantees):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### xAI / Grok API key

Do not commit `.env` (gitignored). Keep `XAI_API_KEY` blank for offline work.

```bash
# 1) Optional: copy example (or let the first run create .env)
cp .env.example .env

# 2) For live Grok only — set a real key
#    XAI_API_KEY=xai-<your-real-key>
#    XAI_MODEL=grok-3

# 3) GALATIQ_PERMIT_SECRET may be blank or removed.
#    First run creates a strong secret and writes it to .env.
#    It signs PaymentPermit tokens so the LLM cannot authorize pay alone.

# 4) Run the CLI. Missing/rejected key → prompt for key or offline stub.
uv run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub

# 5) Live Grok pytest (optional)
uv run pytest -m live_grok -q
```

For GitHub Actions live job, add repo secret `XAI_API_KEY`.

### CLI vs VP desk (important)

The CLI has **no interactive human reject**. Offline stub rules:

- Under $10k, clean → auto-approve and pay
- Over $10k, clean → stub “VP scrutiny” may approve or reject
- Validation issues → reject (no pay)

Human escalate / reject / VP pay is in the **Control Centre** (`web/`), not the CLI. Case-sim VP workflows use the workbench API.

## Quality gates (Meta VP)

Run these before review. Makefile wraps `uv run`.

```bash
make sync       # uv sync --extra dev
make lint       # ruff check + ruff format --check
make smoke      # pytest -m smoke
make blackbox   # pytest -m black_box
make whitebox   # pytest -m white_box
make quality    # lint + full offline pytest
make report     # one-page quality summary
make cli-stub   # invoice1 offline summary
```

| Gate | What it covers |
|---|---|
| Smoke | Fast CLI + case-sim stub checks |
| Black box | Case sim W1–W10, corpus smoke/manifest, e2e |
| White box | Parsers, policy, domain, hardening, outbox, Grok fixtures |
| Lint | Ruff check + format (no Black) |
| Quality | Lint + all offline tests (`not live_grok`) |

## Case brief compliance

Mapped 1:1 to [galatiq-case-invoices](https://github.com/galatiq-ai/galatiq-case-invoices):

| Brief requirement | Where |
|---|---|
| 4 stages: Ingestion → Validation → Approval → Payment | `StageName` + agents/workers |
| Inventory seed WidgetA/B, GadgetX, FakeItem | `case_brief.INVENTORY_SEED` / `scripts/setup_inventory.py` |
| Scenario table (1001/1002/1003/1008/1009/1016) | `--sim=case` + parsers |
| `mock_payment(vendor, amount)` | `case_brief.mock_payment` → `MockPaymentGateway` |
| Grok `api_key="your_key"` / `grok-3` | `.env.example` + `llm_grok.py` |
| CLI `python main.py --invoice_path=data/invoices/invoice1.txt` | `main.py` + `data/invoices/invoice1.txt` |
| Structured logs / results | JSONL events + CLI JSON |
| Offline / no external payment APIs | mock gateway + stub LLM |
| PDF/TXT/CSV/JSON(+XML) corpus | `data/invoices/` |

## How to use the Control Centre

1. Open **Capture**. Process all samples or upload files.
2. Open **Exceptions**. Fix low-confidence fields. Approve and pay, or escalate to VP.
3. Switch **Working as** to **VP Approver**. Open **Approvals**. Approve or decline.
4. Open **Audit** for the ledger.

Analysts cannot see Approvals. VPs own that desk. Role switcher is **demo auth only** (unsigned cookie) — not real RBAC.

**Case Lab:** open [http://localhost:8000/sim](http://localhost:8000/sim). It is not in the product nav.

## Architecture

This repo is a custom multi-stage pipeline with SQLite durable queues, a human workbench, optional Grok, and a non-LLM PaymentPermit fence. It is not LangGraph.

```text
Invoice files
  → Deterministic parsers (+ optional LLM repair/extract)
  → Invariant + inventory validation (hard/soft issue codes)
  → Approval (rules/stub or Grok critique for >$10k) / HITL workbench
  → PolicyEngine issues HMAC PaymentPermit (required)
  → Payment saga + outbox flush to JSONL (refuses naked / invalid permits)
  → JSONL + workbench audit events + metrics_snapshot.json
```

### Hardening (VP-review fixes)

- Durable permit nonces live in SQLite `consumed_permits`.
- `GALATIQ_PERMIT_SECRET` is required. Short or placeholder values fail.
- CI runs ruff and offline pytest. Optional `live_grok` job needs `XAI_API_KEY`.
- One orchestration path: `extract_and_validate` uses the same queue drain as the CLI.
- Outbox publisher flushes saga rows to JSONL (`PaymentOutboxPublished`).
- Metrics cover stage latency, outcomes, VP reflection, and LLM tokens.
- `--max_steps` sets the drain budget. Backlog emits `DrainBudgetExceeded`.
- Grok uses JSON `response_format`. Incorrect keys fail closed (no silent parser fallback).

| Layer | What |
|---|---|
| Agents | Ingestion, Validation, Approval, Payment workers (custom queues) |
| Policy fence | `PaymentPermit` HMAC — LLM text cannot authorize pay |
| Resilience | Timeouts, retries+jitter, circuit breakers, DLQ |
| Persistence | Durable stage queues (SQLite), payment outbox, workbench DB |
| LLM | Offline stub (CI golden) + optional live Grok |
| UI | FastAPI Control Centre + Case Lab at `/sim` |
| CLI | `python main.py --invoice_path=...` / `--sim=case` |
| Sim | Case Simulation Contract + fault injection (F1–F3) |
| Tooling | `uv.lock`, Makefile, ruff, pytest markers |

## Evaluation criteria mapping

| Criterion | Evidence |
|---|---|
| **Functionality** | Case Simulation Contract; CLI + workbench |
| **Code Quality** | Protocols, frozen DTOs, ruff gates, hardening tests |
| **Agentic sophistication** | Multi-stage agents, inventory/payment tools, optional Grok |
| **Shipping mindset** | Offline-first MVP; Control Centre as product UI |
| **Presentation** | Business impact mapped to capture→exception→approval→audit |
| **Above/Beyond** | Workbench, role gates, Case Lab, PaymentPermit, fault sims |
| **UI/UX** | AP Control Centre: list→detail, badges, clear next actions |

## Business impact

| Pain today | System response |
|---|---|
| 30% manual error | Schema/inventory guards + human override on low confidence |
| 5-day approvals | Auto path under $10k; VP queue only for risk |
| Payment/audit ambiguity | Idempotent saga + outbox + per-invoice event trail |
| Messy multi-format invoices | Format parsers + LLM extract with self-correction |

## Project layout

```text
main.py                     # Case CLI (+ --sim=case)
invoice_automation/         # Domain, agents, saga, workbench, sim/
web/                        # FastAPI AP Control Centre (product UI)
data/invoices/              # 100-file flat corpus
data/corpus_manifest.jsonl  # Golden expectations
scripts/                    # bootstrap_env, generate_corpus, quality_report
tests/                      # smoke / black_box / white_box markers
spike/schema.sql            # Queue / DLQ / outbox schema
uv.lock                     # Locked dependencies (uv)
Makefile                    # sync, lint, smoke, quality
CLAUDE.md                   # Coding guidelines
# ui/ is deprecated and gitignored — not shipped
```

## Expanded corpus (100 files)

`data/invoices/` holds upstream Galatiq samples plus generated stress files (`invoice_1100+`).

```bash
uv sync --extra dev
uv run python scripts/generate_corpus.py
uv run pytest tests/test_corpus_smoke.py tests/test_corpus_manifest.py -q
uv run python main.py --all --llm=stub
```

## Case Simulation Contract

Workflows W1–W10 live in `invoice_automation/sim/case_contract.py`. One runner serves CLI, pytest, Case Lab, and notebooks.

```bash
uv run python main.py --sim=case --llm=stub
uv run pytest tests/test_case_sim.py -q
```

## Commands cheat sheet

```bash
make sync
make cli-stub
uv run python main.py --invoice_path=data/invoices/invoice1.txt
uv run python main.py --sim=case --llm=stub
make smoke && make blackbox && make whitebox
make quality
make report
uv run uvicorn web.app:app --reload --port 8000
```

See [CLAUDE.md](CLAUDE.md) for coding rules.
