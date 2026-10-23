# SDK Events

[中文](README-zh.md)

Subscribe to events emitted by capabilities actually implemented by this SDK:
instance cache add/update/delete and local instance circuit-breaker transitions.
The optional Pushgateway reports `InstanceThreadEnd` and circuit-breaker
transitions. The example does not emit
rate-limit, lossless, configuration, or watch events.

```bash
./examples/verify.sh --only events
```

Run against a real registry:

```bash
POLARIS_E2E=1 make -C examples/events run \
  ARGS="--server 127.0.0.1:8091 --namespace default --service DiscoverEchoServer"
```

See [test.md](test.md) for the offline verification and
[event documentation](../../docs/events.md) for listener APIs and event fields.
