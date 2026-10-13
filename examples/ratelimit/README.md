# Rate limit example

This example follows the Java/Go remote rate-limit flow: the Provider registers
an HTTP service and calls `LimitAPI.get_quota` for every request. The quota
rules are loaded from Polaris; no rule is hard-coded in the example.

```bash
POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
python examples/ratelimit/provider.py
```

In another terminal:

```bash
POLARIS_SERVER_ADDRESSES=127.0.0.1:8091 \
python examples/ratelimit/client.py --service RateLimitEchoServer
```

Create the `RateLimitEchoServer` service and its `/echo` rate-limit rule in
the Polaris console before starting the Provider.

`verify_ratelimit.sh` creates that local QPS rule, starts the provider, and
checks that a burst receives both `200` and `429`:

```bash
bash examples/ratelimit/verify_ratelimit.sh
```

Cases and pass criteria: [test.md](test.md). Leftover processes and `.logs/`:

```bash
bash examples/ratelimit/cleanup.sh
bash examples/ratelimit/cleanup.sh -f
bash examples/ratelimit/cleanup.sh --dry-run
```

`cleanup.sh` does not delete the rate-limit rule created by the verify script.
