SUBDIRS := cache circuitbreaker loadbalancer mcp multicontext quickstart sdkconfig servicerouter skill
VERIFY_COMMAND := "$(CURDIR)/verify.sh"

include group.mk

.PHONY: verify-e2e verify_e2e.sh logs logs.sh cleanup cleanup.sh

verify-e2e verify_e2e.sh:
	"$(CURDIR)/verify_e2e.sh" $(ARGS)

logs logs.sh:
	"$(CURDIR)/logs.sh" $(ARGS)

cleanup cleanup.sh:
	"$(CURDIR)/cleanup.sh" $(ARGS)
