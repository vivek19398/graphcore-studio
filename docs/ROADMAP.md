# Roadmap

## Shipped in this local Studio prototype

- Drag-and-drop canvas with reusable JSON templates, condition routes and agent handoff flows.
- Supervisor-to-specialist example, Python tools, output inspection, execution trace and run history.
- Structured output with a dependency-free validator and optional Pydantic v2 integration.
- OpenRouter SDK adapter, human approval checkpoints, workflow export/import and local save.
- C++17 sequential scheduler and file checkpoints behind a C ABI, launched with one command.
- Loopback-only server, run input limits, per-launch write token and origin validation.

## Remaining work before production

1. Persisted parallel supersteps, explicit fan-out/join groups, stable reducers, and durable task results.
2. SQLite/PostgreSQL transaction backends, checkpoint fsync policy, integrity checks, schema migration and retention.
3. Streaming provider responses, classified retries, idempotent effect journal, and Python cancellation/deadline propagation.
4. Nested JSON Schema/Pydantic models, user-defined validators, typed output ports, and richer state/secret handling.
5. Run the multi-platform wheel release workflow and verify Linux, macOS, and Windows artifacts before publishing.
6. Trace redaction/export, automated frontend accessibility and visual regression checks, and a full developer guide.
7. Authentication and worker leases only if a remote/team deployment becomes a goal; current Studio remains a local single-user tool.

## Release gates

Pass the compiler-only build and CTest on Linux, macOS and Windows. Test Pydantic-enabled and dependency-free environments, real restart/interrupt recovery, OpenRouter request limits and JSON responses, malformed workflow import, cross-origin write rejection and cancellation behavior. Benchmark native scheduler time separately from Python/model calls. Do not publish an overall speedup figure without comparable workloads and measured data.
