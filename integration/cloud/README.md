# Polaris Python Cloud E2E Packaging

[中文](README-zh.md)

This workflow packages the source tree, examples, integration tests, and an
optional Python dependency runtime for execution on a cloud test host.

```bash
# Local: build a Linux x86_64 / Python 3.12 deployment package
./integration/cloud/build-package.sh

# Cloud: extract and run
tar xzf polaris-python-cloud-*.tar.gz
cd polaris-python-cloud-*
./run-e2e.sh --server <polaris-host>:8091

# Cloud: pack all retained run logs
./pack-logs.sh --all

# Local: securely import and summarize returned logs
./integration/cloud/import-logs.sh <run-id>-logs.tar.gz
```

The default package bundles dependencies and requires only Python 3.12 on the
cloud host. Use `--without-runtime` for a source-only package; that mode requires
`uv` and dependency-index access on the cloud host.

Each run is written below `cloud-runs/<run-id>/` with `manifest.json`,
`environment.txt`, `run.log`, `analysis.txt`, `logs/`, and a snapshot of retained
process records. Tokens are inherited from environment variables and are never
written to the manifest.

By default cloud processes, remote services, and artifacts are retained. Cleanup
is a separate explicit action:

```bash
./integration/cleanup.sh --force --delete-services
```

See [README-zh.md](README-zh.md) for the complete workflow, options, package
manifest, import checks, and troubleshooting order.
