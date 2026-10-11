# Galatiq Invoice Processing System

Version **1.1.1**.

This system automates invoice work for the [Galatiq case](https://github.com/galatiq-ai/galatiq-case-invoices).

The public GitHub repository is [Rinnegan27/galatiq-invoice-system](https://github.com/Rinnegan27/galatiq-invoice-system).

## How to run

Do these steps in order.

### 1. First-time build (install + all checks)

Install [uv](https://docs.astral.sh/uv/) first.

Then run one command from the repo root:

```bash
cd galatiq-invoice-system
make
```

`make` and `make build` do the same work:

1. Sync deps (`uv sync --extra dev`)
2. Lint with ruff (check + format check)
3. Run all offline tests
4. Run the case scenario proof (`docs/scenario_proof.*`)

If any step fails, the build stops.

Pip fallback (no lockfile; then run checks by hand):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make quality
make scenario-proof
```

### 2. Set the environment

Do not commit `.env`. Git ignores this file.

```bash
cp .env.example .env
```

- Leave `XAI_API_KEY` blank for offline work.
- Leave `GALATIQ_PERMIT_SECRET` blank, or remove the line.
- On the first run, the system creates a random HMAC secret and writes it to `.env`.
- For live Grok only, set `XAI_API_KEY=xai-<your-real-key>`.

### 3. Case CLI contract (required path)

The case brief requires this command:

```bash
python main.py --invoice_path=data/invoices/invoice1.txt
```

With `uv` and the offline stub:

```bash
uv run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub
```

You get a short JSON summary. Add `-v` for the full audit.

`data/invoices/invoice1.txt` is an alias of INV-1001.

## Evaluator demo (three steps)

Use these steps for a fast review.

### A. Live Grok

1. Set a real key in `.env`: `XAI_API_KEY=xai-...`
2. Run:

```bash
uv run python main.py --invoice_path=data/invoices/invoice1.txt
```

The default engine is Grok. If the key is missing or bad, the CLI asks for a key or offline stub.

### B. Offline happy path

```bash
uv run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub
```

Expect status `paid` for INV-1001.

### C. Case Simulation Contract

```bash
uv run python main.py --sim=case --llm=stub
```

Expect all W1–W10 workflows to pass.

### Scenario proof artifact

The case README scenario table is checked in under `docs/`:

- [docs/scenario_proof.md](docs/scenario_proof.md) — human table
- [docs/scenario_proof.json](docs/scenario_proof.json) — machine report

Regenerate:

```bash
make scenario-proof
```

## Other common commands

```bash
# All sample invoices (offline)
uv run python main.py --all --llm=stub

# AP Control Centre UI
uv run uvicorn web.app:app --reload --port 8000
# http://localhost:8000
# Case Lab: http://localhost:8000/sim
```

## Aether Helix quality gates

Default build (first time and every full check):

```bash
make
# same as:
make build
```

Faster re-check after deps are already installed:

```bash
make check
# same as:
make quality
```

Other targets:

```bash
make sync
make lint
make smoke
make report
make scenario-proof
```

| Gate | Command | Coverage |
|---|---|---|
| Build (default) | `make` / `make build` | Sync + lint + offline tests + scenario proof |
| Check | `make check` / `make quality` | Lint + offline tests (no sync) |
| Smoke | `make smoke` | Fast CLI + case-sim stub |
| Black box | `make blackbox` | Case sim, corpus, e2e |
| White box | `make whitebox` | Parsers, policy, hardening |
| Lint | `make lint` | Ruff check + format |
| Scenario proof | `make scenario-proof` | Case README invoice matrix |

**Aether Helix** is the in-repo quality persona. It is a project nickname for gates. It is not a product role.

## Grok API note

The case README shows a sketch with `from xai import Grok`.

This project uses the OpenAI-compatible xAI HTTP API instead:

- Base URL: `https://api.x.ai/v1`
- Client: `openai.OpenAI`
- Default model: `grok-3` (see `XAI_MODEL`)

Code: `invoice_automation/adapters/llm_grok.py`.

Offline work uses `--llm=stub`. No live key is required for CI.

## Intentional non-goals

We do not plan these changes:

- Port to LangGraph, CrewAI, or AutoGen. The case allows a custom solution. This repo uses a custom SQLite queue pipeline.
- Expand the deprecated Streamlit `ui/`. Product UI is FastAPI `web/` only.

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

## Case brief compliance (detail)

Mapped 1:1 to [galatiq-case-invoices](https://github.com/galatiq-ai/galatiq-case-invoices):

| Brief requirement | Where |
|---|---|
| 4 stages: Ingestion → Validation → Approval → Payment | `StageName` + agents/workers |
| Inventory seed WidgetA/B, GadgetX, FakeItem | `case_brief.INVENTORY_SEED` |
| Scenario table (1001/1002/1003/1008/1009/1016) | `docs/scenario_proof.*` + `--sim=case` |
| `mock_payment(vendor, amount)` | `case_brief.mock_payment` |
| Grok via xAI API / `grok-3` | `.env.example` + `llm_grok.py` (OpenAI-compatible client) |
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

This project uses a custom multi-stage pipeline. It uses SQLite queues, a workbench, optional Grok, and a non-LLM PaymentPermit fence. It is not LangGraph.

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
- Blank `GALATIQ_PERMIT_SECRET` creates a random secret.
- The system verifies the permit before pay. It consumes the permit only after pay succeeds. Retries stay possible.
- One orchestration path runs through `Pipeline.drain`.
- Grok auth failures fail closed. Due dates from Grok are kept.
- CI uses `uv sync --frozen` plus ruff and offline pytest.

## Project layout

```text
main.py                     # Case CLI
invoice_automation/         # Domain, agents, saga, workbench, sim
web/                        # FastAPI Control Centre
data/invoices/              # 100-file corpus
docs/                       # Scenario proof + evaluator artifacts
tests/                      # smoke / black_box / white_box
uv.lock                     # Locked deps
Makefile                    # default: make / make build (sync + all checks)
CHANGELOG.md                # Release history
CLAUDE.md                   # Coding rules
```

## Tech used

| Layer | Tech |
|---|---|
| Language | Python 3.11+ |
| Package / lock | `uv`, `pyproject.toml`, `uv.lock` |
| Domain models | Pydantic v2 |
| Orchestration | Custom SQLite stage queues (not LangGraph) |
| Inventory / state | SQLite |
| LLM (live) | xAI Grok via OpenAI-compatible API (`openai`, `https://api.x.ai/v1`) |
| LLM (offline) | Deterministic stub parsers |
| PDF text | pdfplumber |
| HTTP | httpx |
| Product UI | FastAPI, uvicorn, Jinja2, python-multipart |
| Data helpers | pandas |
| Config | python-dotenv |
| Quality | pytest, ruff, Makefile, GitHub Actions |
| Payment fence | HMAC `PaymentPermit` (stdlib `hmac` / `hashlib`) |

See [CHANGELOG.md](CHANGELOG.md) for version history. GitHub Releases hold the same notes.

## Evaluation criteria

| Criterion | Evidence |
|---|---|
| Functionality | Case sim; CLI + workbench; `docs/scenario_proof.*` |
| Code quality | Protocols, ruff, Aether Helix gates |
| Agentic sophistication | Multi-stage agents, optional Grok, self-correction |
| Shipping mindset | Offline-first; Control Centre UI |
| Above and beyond | Workbench, Case Lab, PaymentPermit, 100-file corpus |

## How this solution meets the requirements

This build covers the full Galatiq case surface.

| Requirement | How we deliver it |
|---|---|
| Four stages: Ingestion → Validation → Approval → Payment | Durable SQLite stage queues + workers in `invoice_automation/agents/` |
| Inventory seed (WidgetA/B, GadgetX, FakeItem) | `case_brief.INVENTORY_SEED` reseeds on pipeline start |
| Scenario table (1001, 1002, 1003, 1008, 1009, 1016, …) | `docs/scenario_proof.*` + `--sim=case` (W1–W10) + 100-file corpus |
| `mock_payment(vendor, amount)` | Case-brief mock → `MockPaymentGateway` + payment saga |
| Grok / offline LLM | Default CLI = Grok; `--llm=stub` for CI |
| CLI contract path | `python main.py --invoice_path=data/invoices/invoice1.txt` |
| Structured audit trail | JSONL events, outbox publish, metrics snapshot |
| Offline / no live payment rails | Stub LLM + mock gateway |
| Multi-format corpus | txt / json / csv / xml / pdf under `data/invoices/` |
| High-value scrutiny | Stub/Grok reflection over $10k; Control Centre Approvals desk |
| Human-in-the-loop | Exceptions, escalate, approve/decline in FastAPI `web/` |
| Payment cannot be LLM-authorized | HMAC `PaymentPermit`; nonce consumed only after successful pay |
| Fail-closed extraction | Missing totals and bad keys do not silently succeed |
| Reproducible tooling | `uv.lock`, Makefile, ruff, smoke / black_box / white_box markers |

## Changelog and releases

- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releases: https://github.com/Rinnegan27/galatiq-invoice-system/releases

Current package version: **1.1.1** (`pyproject.toml` and `invoice_automation.__version__`).

See [CLAUDE.md](CLAUDE.md) for coding rules.
