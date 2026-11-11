# Integration Fixtures

[中文](README-zh.md)

These applications exist only for integration verification. They may contain
fault injection, compatibility checks, long-running lifecycle control, or other
complex behavior that would make a public example harder to understand.

Fixture code may depend on `integration/`. Public code under `examples/` must not
import fixtures or require fixture-specific environment switches.
