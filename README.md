# Galatiq Invoice Processing System

Version **1.1.1**. Multi-agent AP automation for the [Galatiq case](https://github.com/galatiq-ai/galatiq-case-invoices).

## How to run

Do these steps first.

### 1. Install

```bash
# Install uv: https://docs.astral.sh/uv/
cd galatiq-invoice-system
uv sync --extra dev
```

Pip fallback (no lockfile):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Environment

Do not commit `.env`. It is gitignored.

```bash
cp .env.example .env
```

- Leave `XAI_API_KEY` blank for offline work.
- Leave `GALATIQ_PERMIT_SECRET` blank or remove the line.
- On first run, the system creates a random HMAC secret and writes it to `.env`.
- For live Grok only, set `XAI_API_KEY=xai-<your-real-key>`.

### 3. Run one invoice (offline)

```bash
uv run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub
```

You get a short JSON summary. Add `-v` for the full audit dump.

### 4. Other common commands

```bash
# Default engine is Grok (prompts for key or offline if missing)
uv run python main.py --invoice_path=data/invoices/invoice1.txt

# All sample invoices (offline)
uv run python main.py --all --llm=stub

# Case Simulation Contract W1–W10
uv run python main.py --sim=case --llm=stub

# AP Control Centre UI
uv run uvicorn web.app:app --reload --port 8000
# http://localhost:8000
# Case Lab: http://localhost:8000/sim
```

### 5. Aether Helix quality gates

```bash
make sync
make lint
make smoke
make quality
make report
```

---

## How this solution meets the requirements

This build covers the full Galatiq case surface — not a demo stub.

| Requirement | How we deliver it |
|---|---|
| Four stages: Ingestion → Validation → Approval → Payment | Durable SQLite stage queues + workers in `invoice_automation/agents/` |
| Inventory seed (WidgetA/B, GadgetX, FakeItem) | `case_brief.INVENTORY_SEED` reseeds on pipeline start |
| Scenario table (1001, 1002, 1003, 1008, 1009, 1016, …) | Parsers + `--sim=case` (W1–W10) + 100-file corpus |
| `mock_payment(vendor, amount)` | Case-brief mock → `MockPaymentGateway` + payment saga |
| Grok / offline LLM | Default CLI = Grok; `--llm=stub` for CI; missing/bad key prompts for key or offline |
| CLI contract path | `python main.py --invoice_path=data/invoices/invoice1.txt` |
| Structured audit trail | JSONL events, outbox publish, metrics snapshot |
| Offline / no live payment rails | Stub LLM + mock gateway; no external pay APIs |
| Multi-format corpus | txt / json / csv / xml / pdf under `data/invoices/` |
| High-value scrutiny | Stub/Grok reflection over $10k; Control Centre Approvals desk |
| Human-in-the-loop | Exceptions, escalate, approve/decline in FastAPI `web/` |
| Payment cannot be LLM-authorized | HMAC `PaymentPermit`; nonce consumed only after successful pay |
| Fail-closed extraction | Missing totals and bad keys do not silently “succeed” |
| Reproducible tooling | `uv.lock`, Makefile, ruff, smoke / black_box / white_box markers |

**Aether Helix** is the in-repo quality persona: smoke, black-box, white-box, lint, and the one-page `make report` summary. It is a project nickname for gates — not a product role.

## What this system does

Acme Corp loses about **$2M/year** on manual invoice work (**30% error rate**, **5-day cycle**).

Flow: **Capture → Exceptions → Approvals → Audit and payments**

Product UI is the FastAPI **AP Control Centre** in `web/`. Streamlit `ui/` is deprecated and not in git.

### GALATIQ_PERMIT_SECRET

This secret signs **PaymentPermit** tokens. The LLM cannot authorize pay alone.

| State | Behavior |
|---|---|
| Blank or missing | Create a random hex secret. Save it to `.env`. |
| Placeholder or too short | Reject. |
| Set to a strong value | Use it. |

### CLI vs Approvals desk

The CLI has no interactive human reject.

- Clean invoice ≤ $10k → auto-approve and pay (stub)
- Clean invoice > $10k → stub high-value rules may approve or reject
- Validation issues → reject

Human escalate / reject / Approvals-desk pay is in the Control Centre only.

Role switcher in the UI is **demo auth only** (unsigned cookie).

## Aether Helix quality gates

| Gate | Command | Coverage |
|---|---|---|
| Smoke | `make smoke` | Fast CLI + case-sim stub |
| Black box | `make blackbox` | Case sim, corpus, e2e |
| White box | `make whitebox` | Parsers, policy, hardening |
| Lint | `make lint` | Ruff check + format |
| Full | `make quality` | Lint + all offline tests |

## Case brief compliance (detail)

Mapped 1:1 to [galatiq-case-invoices](https://github.com/galatiq-ai/galatiq-case-invoices):

| Brief requirement | Where |
|---|---|
| 4 stages: Ingestion → Validation → Approval → Payment | `StageName` + agents/workers |
| Inventory seed WidgetA/B, GadgetX, FakeItem | `case_brief.INVENTORY_SEED` |
| Scenario table (1001/1002/1003/1008/1009/1016) | `--sim=case` + parsers |
| `mock_payment(vendor, amount)` | `case_brief.mock_payment` |
| Grok `api_key="your_key"` / `grok-3` | `.env.example` + `llm_grok.py` |
| CLI `python main.py --invoice_path=data/invoices/invoice1.txt` | `main.py` |
| Structured logs / results | JSONL events + CLI JSON |
| Offline / no external payment APIs | mock gateway + stub LLM |
| PDF/TXT/CSV/JSON(+XML) corpus | `data/invoices/` |

## How to use the Control Centre

1. Open **Capture**. Process samples or upload files.
2. Open **Exceptions**. Fix fields. Approve and pay, or escalate.
3. Switch **Working as** to **Approver**. Open **Approvals**.
4. Open **Audit** for the ledger.

Case Lab: [http://localhost:8000/sim](http://localhost:8000/sim) (not in product nav).

## Architecture

Custom multi-stage pipeline with SQLite queues, workbench, optional Grok, and a non-LLM PaymentPermit fence. Not LangGraph.

```text
Invoice files
  → Deterministic parsers (+ optional LLM extract)
  → Inventory + invariant validation
  → Approval (stub/Grok) / HITL workbench
  → HMAC PaymentPermit (required)
  → Payment saga + outbox → JSONL
```

### Hardening notes

- Permit nonces live in SQLite `consumed_permits`.
- Blank `GALATIQ_PERMIT_SECRET` auto-creates a random secret.
- Permit is verified before pay and consumed only after pay succeeds (retries stay possible).
- One orchestration path via `Pipeline.drain`.
- Grok auth failures fail closed. Due dates from Grok are kept.
- CI uses `uv sync --frozen` plus ruff and offline pytest.

## Project layout

```text
main.py                     # Case CLI
invoice_automation/         # Domain, agents, saga, workbench, sim
web/                        # FastAPI Control Centre
data/invoices/              # 100-file corpus
tests/                      # smoke / black_box / white_box
uv.lock                     # Locked deps
Makefile                    # sync, lint, quality
CLAUDE.md                   # Coding rules
```

## Evaluation criteria

| Criterion | Evidence |
|---|---|
| Functionality | Case sim; CLI + workbench; full requirement map above |
| Code quality | Protocols, ruff, Aether Helix gates |
| Agentic sophistication | Multi-stage agents, optional Grok, self-correction |
| Shipping mindset | Offline-first; Control Centre UI |
| Above and beyond | Workbench, Case Lab, PaymentPermit, 100-file corpus |

See [CLAUDE.md](CLAUDE.md) for coding rules.
