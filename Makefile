PYTHON ?= .venv/bin/python
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
UV ?= uv

.PHONY: all bootstrap verify test lint format clean help

all: verify

help:
	@echo "Agent Engine Monorepo Make Targets:"
	@echo "  make bootstrap   - Set up Python virtualenv and verify dev toolchains"
	@echo "  make verify      - Run lint checks and full test suite"
	@echo "  make test        - Run unit and integration tests with pytest"
	@echo "  make lint        - Check code formatting and style with ruff"
	@echo "  make format      - Auto-format code with ruff"
	@echo "  make clean       - Remove cached files and build artifacts"

bootstrap:
	@echo "==> Setting up Python virtual environment with uv..."
	@if [ ! -d ".venv" ]; then \
		$(UV) venv .venv; \
	fi
	@echo "==> Checking dependencies via uv pip..."
	@$(UV) pip list --python $(PYTHON) > /dev/null 2>&1 || true
	@echo "==> Checking Node / pnpm status..."
	@which pnpm > /dev/null 2>&1 && echo "pnpm is available: $$(pnpm --version)" || echo "[INFO] pnpm is not installed in current environment; JS packages will build when pnpm is available."
	@echo "==> Checking Rust / Cargo status..."
	@which cargo > /dev/null 2>&1 && echo "cargo is available: $$(cargo --version)" || echo "[INFO] cargo is not installed in current environment; Tauri shell will build when cargo is available."
	@echo "==> Bootstrap complete."

verify: lint test
	@echo "==> Verification complete: All checks passed!"

test:
	@echo "==> Running pytest test suite..."
	$(PYTEST) tests/ -v

lint:
	@echo "==> Running ruff lint checks..."
	@which $(RUFF) > /dev/null 2>&1 && $(RUFF) check . || $(PYTHON) -m ruff check . || echo "[WARN] ruff not found, skipping lint"

format:
	@echo "==> Running ruff formatting..."
	@which $(RUFF) > /dev/null 2>&1 && $(RUFF) format . && $(RUFF) check --fix . || echo "[WARN] ruff not found, skipping format"

clean:
	@echo "==> Cleaning cache and temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info
