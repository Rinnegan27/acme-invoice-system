# Galatiq invoice system — operator targets (uv primary).
.PHONY: sync lint fmt test smoke blackbox whitebox quality cli-stub report scenario-proof

UV ?= uv
PYTEST_ENV = GALATIQ_PERMIT_SECRET=ci-test-secret-do-not-use-in-prod

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

quality: lint
	$(PYTEST_ENV) $(UV) run pytest -q -m "not live_grok"

cli-stub:
	$(PYTEST_ENV) $(UV) run python main.py --invoice_path=data/invoices/invoice1.txt --llm=stub

report:
	$(PYTEST_ENV) $(UV) run python scripts/quality_report.py

scenario-proof:
	$(PYTEST_ENV) $(UV) run python scripts/scenario_proof.py
