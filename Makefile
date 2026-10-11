.DEFAULT_GOAL := help
NEBULA_DIR := .nebula
RUN := uv run --frozen --project $(NEBULA_DIR)
NEBULA := $(RUN) python -m nebula
BUMP ?= auto
REF ?=

.PHONY: help setup check lint test docs repo-plan repo-apply changelog release-plan release template-update
help: ## List commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
setup: ## Install locked tools and local Git hooks idempotently
	$(NEBULA) setup
check: ## Run lint, tests, secret scan, documentation, and project checks
	$(NEBULA) check
lint: ## Check Python style
	$(RUN) ruff check $(NEBULA_DIR)
	$(RUN) ruff format --check $(NEBULA_DIR)
test: ## Run tooling tests
	$(RUN) pytest $(NEBULA_DIR)/tests
docs: ## Build documentation with warnings treated as errors
	$(RUN) sphinx-build -W --keep-going -b html docs docs/_build/html
repo-plan: ## Compare declared GitHub settings and protections
	$(NEBULA) repo plan
repo-apply: ## Reconcile GitHub settings, preserving stronger protection
	$(NEBULA) repo apply
changelog: ## Generate docs/CHANGELOG.md from accepted main history
	$(NEBULA) changelog
release-plan: ## Preview next SemVer release
	$(NEBULA) release plan --bump $(BUMP)
release: ## Prepare, check, and merge a release PR; publish through CI
	$(NEBULA) release run --bump $(BUMP)
template-update: ## Update from a pinned template release on a new branch
	$(NEBULA) template-update $(if $(REF),--ref $(REF),)

-include Makefile.project
