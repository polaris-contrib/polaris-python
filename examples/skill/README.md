# Published Skills

[中文](README-zh.md)

Query an existing published Skill, list matching resources and download its ZIP package
through a separate Skill gRPC connection. Offline verification also starts a new context
and checks network-error fallback using complete persisted payloads.
With `--mounted-service`, the example first discovers that service, resolves its mounted
Skill, and prefers the mounted version over `--version`; an empty version uses active.

```bash
./examples/verify.sh --only skill
POLARIS_SERVER_ADDRESS=<host>:8091 POLARIS_SERVICE_TOKEN=<service-token> \
POLARIS_SKILL_SERVER_ADDRESS=<host>:8094 POLARIS_SKILL_NAME=<published-name> \
POLARIS_SKILL_NAMESPACE=default \
./examples/verify_e2e.sh --only skill
```

`POLARIS_SKILL_TOKEN` defaults to `POLARIS_TOKEN`; `POLARIS_SKILL_VERSION` may select
a published version. These Skill environment variables are example options, not automatic
SDK configuration overrides. The real example reads only and does not upload or publish.

```bash
POLARIS_E2E=1 make -C examples/skill run \
  ARGS="--skill-server <host>:8094 --namespace default --name lookup"
```

See [test.md](test.md) for checks and artifacts, and [AI registry APIs](../../docs/ai-registry.md)
for code configuration, version selection and fallback behavior.
