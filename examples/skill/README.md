# Published Skills

[中文](README-zh.md)

Query an existing published Skill, list matching resources and download its ZIP package
through a separate Skill gRPC connection. Complete persisted payloads support
network-error fallback for queries and downloads; lists do not fall back.
With `--mounted-service`, the example first discovers that service, resolves its mounted
Skill, and prefers the mounted version over `--version`; an empty version uses active.

`POLARIS_SKILL_TOKEN` defaults to `POLARIS_TOKEN`; `POLARIS_SKILL_VERSION` may select
a published version. These Skill environment variables are example options, not automatic
SDK configuration overrides. The example reads only and does not upload or publish.
Set `--skill-server` or `POLARIS_SKILL_SERVER_ADDRESS` for the Skill connection;
the demo default is `127.0.0.1:8094`. Select an existing published resource with
`--namespace`, `--name` and optionally `--version`.

From the repository root:

```bash
make -C examples run DEMO=skill ARGS='--skill-server 127.0.0.1:8094 --namespace default --name lookup'
```

See [AI registry APIs](../../docs/guides/ai-registry.md) for code configuration,
version selection and fallback behavior.

## Logs And Cleanup

From the repository root:

```bash
make -C examples logs ARGS='--only skill --latest --tail 30'
make -C examples cleanup ARGS='--only skill --dry-run'
make -C examples cleanup ARGS='--only skill'
```

Example logs and backups live in this demo's `.logs/run-<timestamp>-<id>/`;
direct `python main.py` runs use `.logs/manual/`. Cleanup confirms by default and
only stops recorded demo PIDs and removes local generated artifacts. It does not
delete remote services or published Skills.

## Verify

From the repository root, run `./integration/verify.sh --only skill`, or
`./integration/verify_e2e.sh --only skill` against a real registry. Test steps,
E2E fixture behavior and integration test artifacts are documented in
[integration/scenarios/skill/test.md](../../integration/scenarios/skill/test.md).
