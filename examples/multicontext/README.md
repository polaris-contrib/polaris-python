# Multiple Contexts

Creates two independent SDK contexts with separate:

- addresses and tokens
- client IDs and event loops
- registration and heartbeat tasks
- cache and log directories

The first context is deregistered and destroyed while the second continues heartbeats
and discovery. The second context is then cleaned up.

## Verify

```bash
./verify.sh
```

The offline verifier uses a fake registry boundary and checks:

- isolated client IDs, channels, requests, and instances
- heartbeat after one context is destroyed
- API rejection after destruction
- release of threads, streams, cache locks, plugins, and log handles

## Real Registry

```bash
export POLARIS_E2E=1
export POLARIS_FIRST_SERVER=127.0.0.1:8091
export POLARIS_SECOND_SERVER=127.0.0.1:8091
export POLARIS_FIRST_SERVICE_TOKEN=service-token
export POLARIS_SECOND_SERVICE_TOKEN=service-token

./run.sh --namespace default --service multicontext-example
```

Both processes use their own `consumer.localCache.persistDir` and log directory.
Destroying one context does not close the other.

## Logs And Cleanup

```bash
./logs.sh --latest --tail 30
./cleanup.sh --force
```
