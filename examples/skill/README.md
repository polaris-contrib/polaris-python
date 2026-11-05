# Published Skills

[中文](README-zh.md)

Query an existing published Skill, list matching resources and download its ZIP package
through a separate Skill gRPC connection. Offline verification also starts a new context
and checks network-error fallback using complete persisted payloads.
With `--mounted-service`, the example first discovers that service, resolves its mounted
Skill, and prefers the mounted version over `--version`; an empty version uses active.

```bash
./examples/verify.sh --only skill
POLARIS_SERVER_ADDRESS=<host>:8091 \
./examples/verify_e2e.sh --only skill
```

`POLARIS_SKILL_TOKEN` defaults to `POLARIS_TOKEN`; `POLARIS_SKILL_VERSION` may select
a published version. These Skill environment variables are example options, not automatic
SDK configuration overrides. The real example reads only and does not upload or publish.
The Skill address defaults to the registry host on port 8094. In the E2E verifier,
`POLARIS_SKILL_NAMESPACE` defaults to the isolated E2E namespace for automatic discovery
and fixtures; when `POLARIS_SKILL_NAME` is supplied without a namespace, `default` is used.
If no name is supplied, verification selects the first published resource in that
namespace. If none exists, E2E creates and publishes a
persistent `polaris-python-e2e-skill-fixture` through the commercial console API and
reuses it on later runs. The SDK API itself remains read-only.

```bash
POLARIS_E2E=1 make -C examples/skill run \
  ARGS="--skill-server <host>:8094 --namespace default --name lookup"
```

See [test.md](test.md) for checks and artifacts, and [AI registry APIs](../../docs/guides/ai-registry.md)
for code configuration, version selection and fallback behavior.
