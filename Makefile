# Canonical commands for GNOME AI Panel (see .pipeline/PLAN.md, section "Commands").
# All targets are non-interactive.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
RUFF   := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
NPX    := npx --no-install

SCHEMAS_DIR   := extension/schemas
ESLINT_PATHS  := app/ui extension tests/ui tests/gjs scripts eslint.config.mjs playwright.config.mjs
PY_COMPILE    := $(wildcard app mcp)

ARGS ?=

define not_implemented
	@echo "make $@: not implemented yet"
endef

.PHONY: help setup build lint test test-py test-gjs test-ui test-shell run run-headless \
        stop cli install uninstall vendor

help:
	@echo "Targets: setup build lint test test-py test-gjs test-ui test-shell run run-headless"
	@echo "         stop cli install uninstall vendor"

setup:
	scripts/check-deps.sh
	python3 -m venv --system-site-packages $(VENV)
	$(PIP) install --disable-pip-version-check -q -r requirements-dev.txt
	npm ci --no-audit --no-fund
	$(NPX) playwright install webkit chromium

build:
	@if [ -d $(SCHEMAS_DIR) ]; then glib-compile-schemas $(SCHEMAS_DIR); \
	else echo "build: no $(SCHEMAS_DIR) yet, skipping schema compilation"; fi
	$(PY) -m compileall -q $(PY_COMPILE)
	@if [ -f extension/metadata.json ]; then \
		mkdir -p dist && \
		gnome-extensions pack extension --force --extra-source=lib --out-dir=dist; \
	else echo "build: no extension/ yet, skipping extension pack"; fi

lint:
	$(RUFF) check .
	$(RUFF) format --check .
	$(NPX) eslint --max-warnings 0 --no-error-on-unmatched-pattern $(ESLINT_PATHS)
	@if [ -d $(SCHEMAS_DIR) ]; then glib-compile-schemas --strict --dry-run $(SCHEMAS_DIR); \
	else echo "lint: no $(SCHEMAS_DIR) yet, skipping schema check"; fi

test: test-py test-gjs test-ui

# The private bus of dbus-run-session and everything it activates (portals, keyring, gvfs)
# get a temporary XDG_RUNTIME_DIR (mktemp -d, mode 0700) instead of /run/user/<uid>.
test-py:
	@rt=$$(mktemp -d "$${TMPDIR:-/tmp}/ai-panel-test-runtime.XXXXXX") || exit 1; \
	env -u GNOME_KEYRING_CONTROL -u SSH_AUTH_SOCK -u WAYLAND_DISPLAY -u AT_SPI_BUS_ADDRESS \
		XDG_RUNTIME_DIR="$$rt" GIO_USE_VFS=local \
		xvfb-run -a -s "-screen 0 1920x1080x24" dbus-run-session -- $(PYTEST) -q; \
	rc=$$?; rm -rf --one-file-system -- "$$rt"; exit $$rc

test-gjs:
	gjs -m tests/gjs/run.js

# PW_BROWSER unset: WebKit when it can launch, otherwise Chromium with a warning on stderr
# (scripts/pick-browser.mjs). PW_BROWSER set: used as is, without fallback.
test-ui:
	@browser=$$(node scripts/pick-browser.mjs) && echo "test-ui: PW_BROWSER=$$browser" && \
		PW_BROWSER=$$browser $(NPX) playwright test --pass-with-no-tests

test-shell:
	$(not_implemented)

run:
	scripts/run.sh

run-headless:
	scripts/run-headless.sh

stop:
	scripts/stop.sh

# Silent recipe: stdout carries only the CLI output (e.g. JSON).
cli:
	@$(PY) -m app.cli $(ARGS)

install:
	$(not_implemented)

uninstall:
	$(not_implemented)

vendor:
	node scripts/vendor.mjs
