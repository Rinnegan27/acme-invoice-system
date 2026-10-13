# Acme invoice system — operator targets (uv primary).
#
# First-time / full build:
#   make
#   make build
#
# Both install deps, then run ruff, offline tests, and scenario proof.

.DEFAULT_GOAL := build

.PHONY: all build sync lint fmt test smoke blackbox whitebox quality check cli-stub report scenario-proof ledger ledger-live uat

UV ?= uv
PYTEST_ENV = GALATIQ_PERMIT_SECRET=ci-test-secret-do-not-use-in-prod

# Default target. Sync deps, then run all offline checks.
all: build

build: sync quality scenario-proof
	@echo "Build checks passed (sync + lint + tests + scenario-proof)."

sync:
	$(UV) sync --extra dev

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test:
	$(PYTEST_ENV) $(UV) run pytest -q -m "not live_grok"

smoke:
	$(PYTEST_ENV) $(UV) run pytest -q -m smoke

blackbox:
	$(PYTEST_ENV) $(UV) run pytest -q -m black_box

whitebox:
	$(PYTEST_ENV) $(UV) run pytest -q -m white_box

# Lint + all offline tests (no sync). Use after deps are installed.
quality: lint
	$(PYTEST_ENV) $(UV) run pytest -q -m "not live_grok"

# Alias for quality (common CI name).
check: quality

cli-stub:
	$(PYTEST_ENV) GALATIQ_PROFILE=case $(UV) run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub --profile=case

report:
	$(PYTEST_ENV) $(UV) run python scripts/quality_report.py

scenario-proof:
	$(PYTEST_ENV) $(UV) run python scripts/scenario_proof.py

# Offline UAT harness (docs/uat_test_cases.md).
uat:
	$(PYTEST_ENV) $(UV) run pytest -q tests/test_uat_scenarios.py

# Sequential case-core ledger (1× seed, stub). STOCK_MULT / LEDGER_LLM override.
ledger:
	$(PYTEST_ENV) STOCK_MULT=$${STOCK_MULT:-1} LEDGER_LLM=$${LEDGER_LLM:-stub} \
		$(UV) run python scripts/run_stateful_ledger_live_grok.py

# Live Grok ledger (default 15× seed so sequential draws stay non-negative).
ledger-live:
	$(PYTEST_ENV) STOCK_MULT=$${STOCK_MULT:-15} LEDGER_LLM=grok \
		$(UV) run python scripts/run_stateful_ledger_live_grok.py
