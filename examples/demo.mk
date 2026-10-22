# Shared targets for one demo directory. Mirrors the Go examples:
# build writes ./bin, run executes it, package archives that demo.

UV ?= uv
ARGS ?=
DEMO_MAIN ?= main.py
DEMO_NAME ?= $(notdir $(CURDIR))

REPO_ROOT := $(shell dir="$(CURDIR)"; while [ "$$dir" != "/" ] && [ ! -f "$$dir/pyproject.toml" ]; do dir=$$(dirname "$$dir"); done; printf '%s\n' "$$dir")

.PHONY: build build-x86 package run verify clean

build:
	@uv_bin=$$(command -v $(UV)); \
	printf '%s\n' \
		'#!/bin/sh' \
		'set -eu' \
		'HERE=$$(CDPATH= cd -- "$$(dirname "$$0")" && pwd)' \
		'ROOT=$$HERE' \
		'while [ "$$ROOT" != "/" ] && [ ! -f "$$ROOT/pyproject.toml" ]; do' \
		'  ROOT=$$(dirname "$$ROOT")' \
		'done' \
		'if [ ! -f "$$ROOT/pyproject.toml" ]; then' \
		'  echo "place this demo inside a polaris-python checkout" >&2' \
		'  exit 1' \
		'fi' \
		'cd "$$ROOT"' \
		"exec $$uv_bin run --locked python \"\$$HERE/$(DEMO_MAIN)\" \"\$$@\"" \
		> "$(CURDIR)/bin"
	@chmod +x "$(CURDIR)/bin"
	@echo "built $(CURDIR)/bin"

build-x86:
	@os=$$(uname -s); arch=$$(uname -m); \
	if [ "$$os" = "Linux" ] && [ "$$arch" = "x86_64" ]; then \
		$(MAKE) build; \
		cp "$(CURDIR)/bin" "$(CURDIR)/x86-bin"; \
		echo "built $(CURDIR)/x86-bin"; \
	else \
		echo "build-x86 builds this demo on linux/amd64. Current platform is $$os/$$arch." >&2; \
		exit 1; \
	fi

package: build
	@mkdir -p "$(CURDIR)/.build"
	@set -eu; \
	stage="$(CURDIR)/.build/stage"; \
	rm -rf "$$stage"; \
	mkdir -p "$$stage"; \
	cp "$(CURDIR)/bin" "$$stage/bin"; \
	for file in "$(CURDIR)"/*.py "$(CURDIR)"/*.yaml; do \
		[ -f "$$file" ] || continue; \
		name=$$(basename "$$file"); \
		[ "$$name" = "verify.py" ] && continue; \
		cp "$$file" "$$stage/$$name"; \
	done; \
	tar -czf "$(CURDIR)/.build/$(DEMO_NAME).tar.gz" -C "$$stage" .; \
	rm -rf "$$stage"; \
	echo "packaged $(CURDIR)/.build/$(DEMO_NAME).tar.gz"

run: build
	"$(CURDIR)/bin" $(ARGS)

verify:
	@if [ -f "$(CURDIR)/verify.py" ]; then \
		cd "$(REPO_ROOT)" && $(UV) run --locked python "$(CURDIR)/verify.py"; \
	else \
		echo "skip verify: $(CURDIR)"; \
	fi

clean:
	rm -f "$(CURDIR)/bin" "$(CURDIR)/x86-bin" "$(CURDIR)/polaris.log"
	rm -rf "$(CURDIR)/.build" "$(CURDIR)/polaris"
	rm -f "$(CURDIR)"/polaris-*.log
