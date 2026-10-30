---
description: Keep real example E2E resources in the isolated python-integration namespace
globs: examples/**
alwaysApply: false
---

# Real Example E2E Namespace

- Real E2E instances and services created by `examples` use `python-integration` by default.
- Never set `POLARIS_E2E_NAMESPACE=default` for an E2E run. An override is valid only when it names another isolated E2E namespace.
- Keep Skill, MCP, A2A, and other external fixture namespaces separate from the test instance namespace. Use `POLARIS_SKILL_NAMESPACE` and similar resource-specific settings instead of moving test services into a shared namespace.
- Cleanup must use the same isolated namespace and may delete only `polaris-python-e2e-*` services from it.
- Do not change application or library default namespaces merely to satisfy an E2E fixture.
