# Galatiq Invoice Processing System

Production-grade multi-stage invoice pipeline built for the [Galatiq case](https://github.com/galatiq-ai/galatiq-case-invoices).

## Current Status

- **Spike Gate**: Closed (transactional core, atomic idempotency, DLQ, payment saga)
- **Core Pipeline**: Complete (Ingestion → Validation → Approval → Payment)
- LLM: Offline deterministic stub (live Grok available behind `--llm=grok`)
- Event logging: Structured JSONL

## Project Structure

```text
galatiq-invoice-system/
├── spike/                  # Approved transactional core
│   ├── schema.sql
│   ├── models.py
│   ├── queue.py
│   ├── saga.py
│   └── test_spike.py
├── core/                   # End-to-end pipeline
│   ├── models.py
│   ├── llm_stub.py
│   ├── llm_grok.py
│   ├── inventory.py
│   ├── event_log.py
│   ├── workers/
│   ├── pipeline.py
│   ├── main.py
│   └── test_core.py
├── data/
│   └── invoices/           # Place Galatiq sample invoices here
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Rinnegan27/galatiq-invoice-system.git
cd galatiq-invoice-system

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Copy Galatiq sample invoices into data/invoices/

# 5. Run spike tests (must pass)
cd spike
pytest test_spike.py -v

# 6. Run the full pipeline (offline by default)
cd ../core
python main.py --all

# Or single file
python main.py --invoice_path=../data/invoices/invoice_1001.txt

# Live Grok (requires XAI_API_KEY in .env)
python main.py --all --llm=grok
```

## What the system does

1. **Ingestion** – Extracts structured data from txt / json / csv (and messy text)
2. **Validation** – Checks line items against a local inventory database
3. **Approval** – Applies VP-level rules (high-value scrutiny)
4. **Payment** – Uses the saga + outbox pattern from the spike

All decisions are written to `events.jsonl` for full auditability.

## Design History

This implementation follows a rigorous Technical Design Review process (Spike Gate → Core Pipeline). The transactional guarantees (atomic idempotency, DLQ policy, payment saga) were proven before any agent code was written.
