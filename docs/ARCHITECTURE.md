# Architecture

```text
Browser visual canvas (plain HTML/CSS/JS)
             │ local JSON API with per-launch token
Python standard-library HTTP server and run manager
      ├── registered Python / optional Pydantic nodes
      ├── official OpenRouter Python SDK adapter
      └── ctypes C ABI bridge
                  │
C++17 GraphCore runtime
      ├── workflow compiler and node routing
      ├── equality condition node
      └── crash-recoverable local checkpoint files
```

## Source map

- `studio/web/`: dependency-free visual editor; editing, drag-to-place, routes, inspector, templates, history and export.
- `studio/server.py`: loopback-only HTTP API, plugin registration, run workers, workflow/run storage and crash recovery.
- `studio/engine.py`: workflow validation, Python/Pydantic integrations, OpenRouter SDK adapter and C++ graph compilation.
- `studio/templates/`: four runnable design examples.
- `include/graphcore/graphcore.hpp`, `src/graphcore.cpp`: C++ API, sequential scheduler and checkpoint store.
- `include/graphcore/c_api.h`, `src/c_api.cpp`: C ABI used by the Python runtime.
- `python/graphcore/`: Python SDK and asyncio callback bridge.
- `run_studio.py`: one-command native compilation and local startup.

No Node.js, frontend bundler, database, C++ package manager or Python web framework is required. The OpenRouter Python SDK is optional and required only for live model calls; the offline fixture works with the base install. Pydantic remains optional. The canvas is served as local files and does not send workflow data to a remote service.

## Extending nodes

### Python tools

Write a trusted Python module with `register(add_tool)`, then launch using `python3 run_studio.py --plugin path/to/tools.py`. Register a concise name, callable and description. A tool callable receives `(value, config)` and returns a JSON-compatible value. Put credentials and configured library clients in the plugin process environment or its local configuration, never in workflow JSON. Plugin modules are trusted code and run with full user permissions.

### Model adapters

Chat Model and Agent nodes use OpenRouter through the official Python SDK. The `.env` file is loaded at Studio startup and API keys stay out of workflow JSON and execution traces. The graph itself is scheduled by the C++ runtime. Add other providers only after defining their configuration, response/error mapping, limits, cancellation behavior, and tests.

### Structured outputs

Fields currently support flat names and strict primitive/object/array types. The built-in validator works without dependencies. Optional Pydantic mode uses Pydantic v2 models generated from that list. Nested schemas, custom validators, unions and secret fields are future UI features. Python users who need custom object types can validate them inside a registered Python tool.

### Native C++ nodes

Use the C++ builder API for native applications. Native equality-condition nodes can also be constructed through the current C API. The graph designer exposes Python integrations as nodes. A general user-authored native-code plugin system would require a stable ABI, safe compilation strategy, and platform builds; it is not part of this release.

## Performance and scale

C++ removes the scheduler from the Python runtime and makes its transitions native. Python callbacks, model requests, Pydantic and library processing remain Python. For network-bound LLM flows, remote model time will often dominate. Measure complete representative workflows before drawing a speed conclusion.

The UI caps a workflow at 100 nodes and four simultaneous runs. The native runtime executes each graph sequentially and stores state in local files. It is not yet a distributed service, a sandbox, or a database-backed workflow platform.
