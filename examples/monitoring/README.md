# Monitoring

[中文](README-zh.md)

The example starts a loopback HTTP echo endpoint, registers it with Polaris, discovers
it and reports three actual HTTP calls (200, 503, 200). It exports the invocation
metrics through Prometheus pull or Pushgateway push.

```bash
./examples/verify.sh --only monitoring
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/monitoring run ARGS="--mode pull"
```

Pull prints an allocated local `/metric` URL. Default duration is 31 seconds to allow
the first 30-second aggregation; it then prints the metrics and explicitly deregisters.

Push to an explicit gateway:

```bash
POLARIS_E2E=1 POLARIS_SERVER_ADDRESS=127.0.0.1:8091 POLARIS_SERVICE_TOKEN=token \
  make -C examples/monitoring run ARGS="--mode push --push-address 127.0.0.1:9091"
```

Push mode prints the number of successful Pushgateway requests as `pushes` after the
configured interval. Real E2E verification checks that at least one push succeeded.
An empty push address list discovers `Polaris/polaris.pushgateway`.
Invocation reports use `async_update_service_call_result`; synchronous callers use
`update_service_call_result`. No business request interception is automatic.
See [observability](../../docs/observability.md) and [verification](test.md).
