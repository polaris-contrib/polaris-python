# Build and clean demo groups; select one child application to run.

UV ?= uv
ARGS ?=
SUBDIRS ?=
DEMO ?=

REPO_ROOT := $(shell dir="$(CURDIR)"; while [ "$$dir" != "/" ] && [ ! -f "$$dir/pyproject.toml" ]; do dir=$$(dirname "$$dir"); done; printf '%s\n' "$$dir")
EXAMPLES_PYTHON ?= sh "$(REPO_ROOT)/examples/_python.sh"

.PHONY: build build-x86 package run logs cleanup clean

build build-x86 package clean:
	@set -eu; for dir in $(SUBDIRS); do $(MAKE) -C "$(CURDIR)/$$dir" $@; done

run:
	@test -n "$(DEMO)" || { echo 'set DEMO to a child example, such as DEMO=provider' >&2; exit 2; }
	@$(EXAMPLES_PYTHON) "$(REPO_ROOT)/examples/_apps.py" run \
		"$(CURDIR)/$(DEMO)" -- $(ARGS)

logs:
	@$(EXAMPLES_PYTHON) "$(REPO_ROOT)/examples/_apps.py" logs \
		--directory "$(CURDIR)" $(ARGS)

cleanup:
	@$(EXAMPLES_PYTHON) "$(REPO_ROOT)/examples/_apps.py" cleanup \
		--directory "$(CURDIR)" $(ARGS)
