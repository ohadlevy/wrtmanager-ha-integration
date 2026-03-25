# WrtManager Development Makefile
.PHONY: help install dev-install test test-cov lint format type-check clean docs setup-dev

# Default target
help:	## Show this help message
	@echo "WrtManager Home Assistant Integration - Development Commands"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Environment Setup
setup-dev:	## Set up development environment
	./dev-setup.sh

install:	## Install package dependencies
	pip install -e .

dev-install:	## Install package with development dependencies
	pip install -e ".[dev]"

# Testing
test:	## Run tests
	python -m pytest tests/ -v

test-cov:	## Run tests with coverage
	python -m pytest tests/ --cov=custom_components/wrtmanager --cov-report=term-missing --cov-report=html

test-watch:	## Run tests in watch mode (requires pytest-watch: pip install pytest-watch)
	ptw --runner "python -m pytest tests/ --tb=short"

# Code Quality
lint:	## Run all linting checks
	flake8 custom_components/ tests/
	pylint custom_components/ tests/ --disable=all --enable=unused-import,undefined-variable

format:	## Format code with black and isort
	black custom_components/ tests/
	isort custom_components/ tests/

format-check:	## Check if code is properly formatted
	black --check custom_components/ tests/
	isort --check-only custom_components/ tests/

# Pre-commit
pre-commit:	## Run pre-commit hooks on all files
	pre-commit run --all-files

pre-commit-install:	## Install pre-commit hooks
	pre-commit install

# Documentation
docs:	## Build documentation (requires docs/ setup)
	@if [ -f "docs/Makefile" ]; then cd docs && make html; else echo "❌ Documentation not set up. See CONTRIBUTING.md for setup instructions."; fi

docs-serve:	## Serve documentation locally
	@if [ -d "docs/_build/html" ]; then cd docs/_build/html && python -m http.server 8000; else echo "❌ Documentation not built. Run 'make docs' first."; fi

# Utilities
clean:	## Clean build artifacts and cache files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/ .mypy_cache/

check-deps:	## Check for security vulnerabilities in dependencies (requires pip-audit)
	@if command -v pip-audit >/dev/null 2>&1; then pip-audit; else echo "❌ pip-audit not installed. Run 'pip install pip-audit' first."; fi

# Home Assistant specific
ha-validate:	## Validate Home Assistant integration
	python -m homeassistant --script check_config --config . || echo "HA validation requires full HA install"

# Development workflow
dev-check:	## Run full development check (format, lint, test)
	@echo "🔍 Running development checks..."
	@$(MAKE) format-check
	@$(MAKE) lint
	@$(MAKE) test
	@echo "✅ All checks passed!"

dev-fix:	## Fix code issues (format, then run checks)
	@echo "🔧 Fixing code issues..."
	@$(MAKE) format
	@$(MAKE) lint
	@$(MAKE) test
	@echo "✅ Code fixed and validated!"

# Release preparation
release-check:	## Check if ready for release
	@echo "🚀 Checking release readiness..."
	@$(MAKE) dev-check
	@echo "📝 Checking version consistency..."
	@VERSION=$$(grep 'version = ' pyproject.toml | cut -d'"' -f2) && \
	 grep -q "version.*$$VERSION" custom_components/wrtmanager/manifest.json && \
	 echo "✅ Version $$VERSION is consistent across files!"

# CI simulation
ci:	## Simulate CI environment locally
	@echo "🔄 Simulating CI pipeline..."
	@$(MAKE) format-check
	@$(MAKE) lint
	@$(MAKE) test-cov
	@echo "✅ CI simulation completed!"