# GraphCore Studio

**Design local agent workflows on a canvas. Run them with a C++ engine. Extend them with Python.**

GraphCore Studio is an interactive, local-first visual agent framework. Drag nodes onto a canvas, connect agent handoffs, add conditional branches, validate structured output, call Python tools, and pause for human approval. Save and run workflows on your own machine.

## Start Studio

Requirements: Python 3.9.2+ and a C++17 compiler. You do not need CMake, Node.js, Docker, API keys, an internet connection, or a model to try the included workflows.

From the project folder, run one command:

```bash
python3 run_studio.py
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). The launcher compiles the C++ shared library on first run, then opens a server accessible only from your machine. On Windows, use PowerShell in a Visual Studio Developer Terminal with the C++ workload installed:

```powershell
py run_studio.py
```

If Python was installed through the Windows Store and `py` is unavailable, run `python run_studio.py` from the Visual Studio Developer Terminal.

Stop the server with Ctrl+C. Workflows and run history live in `studio/data/`; drafts are saved in this browser. Run `python3 run_studio.py --help` to configure the port, data directory, or Python tool plugins.

### Install the PyPI package

Install the prebuilt package and its OpenRouter/Pydantic runtime dependencies with:

```bash
python -m pip install graphcore-studio
graphcore-studio
```

The wheel bundles the C++ runtime and Studio UI. Source installs build the native runtime and therefore require a C++17 compiler and CMake. The distribution is named `graphcore-studio`; its Python API imports as `graphcore`. Windows, macOS, and Linux wheels are provided for supported architectures.

### Use Pydantic

The built-in structured-output validator works offline. Pydantic v2 is installed by the standard PyPI command above and can be selected as the validation engine. When running directly from a source checkout, install the runtime dependencies with:

```bash
python3 -m pip install -r requirements-models.txt -r requirements-pydantic.txt
python3 run_studio.py
```

On Windows, replace `python3` with `py -3`. Restart Studio after installing packages. The Structured output node shows whether Pydantic is available.

### Use OpenRouter models

The **Chat Model** and **Agent** nodes use GraphCore's model adapter with the official OpenRouter Python SDK, installed automatically by the standard PyPI command. C++ owns graph scheduling, state commits, conditions, and checkpoints; the Python wrapper calls the SDK. The OpenRouter request runs through the project-owned adapter rather than a chain framework.

When running directly from a source checkout, install the runtime dependencies into the Python environment used to run Studio:

```bash
python3 -m pip install -r requirements-models.txt
python3 run_studio.py
```

In Studio, open **Model integrations**, add `OPENROUTER_API_KEY`, and save. Select **OpenRouter** on a Chat Model node and enter a model ID from the [OpenRouter model catalog](https://openrouter.ai/models). Compose system/user/assistant messages and use **Insert variable** to reference workflow inputs and prior node outputs. Studio loads the local `.env` file automatically; secret values are not included in workflow files. The offline fixture needs no SDK, key, or network call.

## Build a workflow

1. Pick a template or drag a node from the left panel.
2. Connect the output dots to the next node's input. Conditional nodes have separate true and false outputs.
3. Select nodes to edit prompts, tools, schemas, and routing rules.
4. Give the workflow JSON input in the panel under the canvas.
5. Run it and inspect the output, state, and per-node trace.
6. Save locally, export the workflow JSON, or approve a saved human checkpoint.

The starter templates cover research and review, structured output, Python tools, a supervisor delegating work to specialist agents, and a chat-model playground. The canvas also supports node search, keyboard undo/redo, zoom, pan, layout changes, validation, and run history.

Prompt templates reference state with `{{input}}`, `{{research}}`, or nested fields such as `{{record.summary}}`. Structured Output defines required fields and types. Python plugins extend the node's registered-tool list without placing executable source code in the workflow document.

## Register a Python library or tool

A plugin is a local, trusted Python module. Studio loads it when the server starts. Import a library in your tool and register an ordinary function:

```python
def register(add_tool):
    from my_library import Client
    client = Client()

    def search(value, config):
        return {"matches": client.search(str(value))}

    add_tool("search", search, "Search our knowledge base")
```

Start Studio with `python3 run_studio.py --plugin path/to/plugin.py`, then select the registered function in a Python Tool node. Plugins execute as the current user; load only modules you trust. The included `studio/example_plugin.py` shows a small plugin.

## What runs where?

```text
Visual editor & local HTTP API
                │ workflow JSON and node registrations
        Python integrations ───── OpenRouter SDK / Pydantic / your packages
                │ Python C ABI
       C++17 graph scheduler ─── conditions / routes / checkpoints
                │
        Local workflow & run files
```

The C++ runtime owns graph validation at compile time, step scheduling, native equality conditions, and checkpoint transitions. Python supplies model and tool integrations and the local editor server. Model and Python tool code executes in Python; agent handoffs are sequential. Performance benefits depend on the workload. No blanket speedup claim is made.

## Build or embed the C++ core

The editor launcher builds the native shared library automatically. To build the core tests and examples as well:

```bash
./scripts/build.sh
```

For CMake users with CMake 3.16 or newer:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Compile a C++ example directly with a compiler:

```sh
c++ -std=c++17 -O2 -Iinclude src/graphcore.cpp examples/approval.cpp -o graphcore_demo
```

The C++ interface is in `include/graphcore/graphcore.hpp`; the experimental C ABI used by Python is in `include/graphcore/c_api.h`.

## Scope and guarantees

This is an early, working local framework. The UI has runnable templates and a native backend. The runtime currently executes one node at a time. Retries can repeat side effects; use idempotency keys in external systems. File checkpoints support local process-restart recovery but do not promise power-loss durability, multiple writers, encryption, or database transactions. Python async cancellation is cooperative only between callbacks. See the [execution contract](docs/SEMANTICS.md).

Parallel fan-out and joins, database-backed persistence, distributed worker coordination, and an authenticated server remain future work. A release workflow now builds CPython wheels for Linux, macOS, and Windows; those hosted builds still need to run before the wheels are verified for release. The local server uses a session token and origin checks, and binds only to loopback; it is not designed for public network exposure.

## Project notes

- [Architecture and extension points](docs/ARCHITECTURE.md)
- [Local UI and runtime semantics](docs/SEMANTICS.md)
- [Roadmap](docs/ROADMAP.md)
- [Local verification record](docs/VALIDATION.md)
- [PyPI release checklist](docs/PYPI_RELEASE.md)
- [Example plugin](studio/example_plugin.py)
