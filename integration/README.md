# Integration

[中文](README-zh.md)

`integration/` owns offline verification, real Polaris E2E, test fixtures,
fault injection, retained process state, artifacts, and cleanup. Public examples
remain small capability demos; complex test-only applications live in
`fixtures/` and never leak into `examples/`.

## Commands

```bash
# Offline verification
./integration/verify.sh
./integration/verify.sh --only quickstart,loadbalancer

# Real registry verification
POLARIS_SERVER_ADDRESS=127.0.0.1:8091 ./integration/verify_e2e.sh --only lossless

# Inspect and clean retained resources
./integration/logs.sh --latest --tail 50
./integration/cleanup.sh --dry-run
./integration/cleanup.sh --force --delete-services
```

Use the targets in `examples/Makefile` for manual examples:
`make -C examples run|logs|cleanup`. Integration commands manage only the
resources recorded under `integration/`.

## Layout

```text
integration/
├── scenarios/        offline verifiers and scenario documentation
├── fixtures/         complex test-only applications and configuration
├── _support.py       test transport and runtime configuration
├── _real_verify.py   real-service assertions
├── _manage.py        scenario selection and process supervision
├── _runtime.py       retained artifacts and process identity
├── verify.sh         offline verification
├── verify_e2e.sh     real-service verification
├── logs.sh           artifact inspection
├── cleanup.sh        process/service/artifact cleanup
├── .logs/            generated run artifacts
└── .runtime/         generated retained-process records
```

See [test.md](test.md) for scenario coverage, environment variables, artifact
semantics, retention, and cleanup.
