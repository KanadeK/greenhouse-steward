PYTHON ?= python
TASK_RUNNER := $(PYTHON) scripts/task.py

.PHONY: help format lint typecheck test audit build quality

help:
	@$(TASK_RUNNER) --help

format:
	@$(TASK_RUNNER) format

lint:
	@$(TASK_RUNNER) lint

typecheck:
	@$(TASK_RUNNER) typecheck

test:
	@$(TASK_RUNNER) test

audit:
	@$(TASK_RUNNER) audit

build:
	@$(TASK_RUNNER) build

quality:
	@$(TASK_RUNNER) quality
