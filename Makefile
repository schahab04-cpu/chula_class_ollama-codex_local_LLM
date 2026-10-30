# GNU Make is available by default on macOS; Windows users need GNU Make
# (for example, from Git Bash or Chocolatey).
ifeq ($(OS),Windows_NT)
PYTHON ?= py -3
else
PYTHON ?= python3
endif

.PHONY: help setup install run test diagnose models voice-install voice-models

help:
	@$(PYTHON) scripts/tasks.py help

setup:
	@$(PYTHON) scripts/tasks.py setup

install:
	@$(PYTHON) scripts/tasks.py install

run:
	@$(PYTHON) scripts/tasks.py run

test:
	@$(PYTHON) scripts/tasks.py test

diagnose:
	@$(PYTHON) scripts/tasks.py diagnose

models:
	@$(PYTHON) scripts/tasks.py models

voice-install:
	@$(PYTHON) scripts/tasks.py voice-install

voice-models:
	@$(PYTHON) scripts/tasks.py voice-models
