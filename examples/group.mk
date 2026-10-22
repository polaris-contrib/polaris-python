# Forward build, package, run, and clean to demo subdirectories.
# A verify.py in this directory runs before the subdirectories.
# The examples root sets VERIFY_COMMAND to run its own verify.sh instead.

UV ?= uv
ARGS ?=
SUBDIRS ?=

REPO_ROOT := $(shell dir="$(CURDIR)"; while [ "$$dir" != "/" ] && [ ! -f "$$dir/pyproject.toml" ]; do dir=$$(dirname "$$dir"); done; printf '%s\n' "$$dir")

.PHONY: build build-x86 package run verify clean

build build-x86 package run clean:
	@set -eu; for dir in $(SUBDIRS); do $(MAKE) -C "$(CURDIR)/$$dir" $@; done

ifdef VERIFY_COMMAND
verify:
	$(VERIFY_COMMAND) $(ARGS)
else
verify:
	@set -eu; \
	if [ -f "$(CURDIR)/verify.py" ]; then \
		cd "$(REPO_ROOT)" && $(UV) run --locked python "$(CURDIR)/verify.py"; \
	fi; \
	for dir in $(SUBDIRS); do $(MAKE) -C "$(CURDIR)/$$dir" verify; done
endif
