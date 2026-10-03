# GraphCore Studio — Product Functionality Catalog

**Audience:** Senior Product Manager, product strategy, design, engineering leadership  
**Purpose:** Provide a detailed inventory of user-visible and developer-facing capabilities, their current behavior, constraints, and product implications.  
**Assessment date:** 30 September 2026  
**Repository package metadata:** `graphcore-studio` 0.2.2. This document describes the repository state inspected on the assessment date, including local, uncommitted work. It does not claim that every item is included in the published 0.2.2 package or has passed release verification.

## 1. Product summary

GraphCore Studio is a local-first visual workflow builder for assembling agent and model workflows. Users edit a graph in a browser, provide JSON input, and run that graph through a C++17 scheduling runtime. Python acts as the integration layer for the browser server, model SDK, registered tools, schema validation, and the Python SDK. OpenRouter is the only live model provider currently implemented. The application can also run deterministic offline demo nodes without a model key or network request.

The intended product promise is to make common agent-workflow patterns accessible through a visual editor while preserving Python extensibility and using C++ for graph transitions. The current implementation is an early, single-user local prototype. It is not yet a hosted team platform, general-purpose agent framework with broad provider coverage, parallel graph executor, secure code sandbox, or production orchestration service.

### Product value today

- A user can visually connect model, agent, condition, tool, schema, approval, and output steps.
- A workflow can call different named OpenRouter model IDs at different nodes.
- Branching, sequential agent handoffs, state updates, interruption, and checkpoint transitions are coordinated by native code.
- A developer can extend integrations with trusted Python functions or use the lower-level Python/C++ APIs.
- Workflows, run records, and checkpoints can remain on the user's machine.
- A local document library and lexical retrieval node are present in the current working tree. Unit and local HTTP run-path checks now pass on macOS; the feature is not yet in a published release or visually verified in the browser UI.

## 2. Status vocabulary

The catalog distinguishes four states so product decisions are based on what is actually available.

| Label | Meaning |
|---|---|
| Implemented in repository | Behavior exists in inspected source. This alone does not imply a successful current build or release. |
| Current working-tree addition | Local changes present in the repository but not yet committed, built, or release-verified. |
| Limited / prototype | Behavior exists but has a material constraint that affects its product promise. |
| Not available | No implementation was found in the inspected code. |

## 3. User segments and primary jobs

### Visual workflow author

Wants to assemble an LLM workflow without writing orchestration code; configure prompts, routes, and outputs; run it locally; and understand why a run succeeded, failed, or paused.

### Python developer

Wants to bring existing Python libraries and business logic into a graph through registered callables, while relying on the native runtime for scheduling and preserving a Python authoring experience.

### C++ developer / framework integrator

Wants to embed a sequential graph runtime in a native application, register C++ callbacks, define routes, run with a step cap, observe events, cancel, and checkpoint local state.

### Product or platform evaluator

Wants to judge whether the tool is safe, maintainable, measurable, and ready for team or enterprise use. Today the code offers a useful local prototype but has significant gaps around parallelism, provider choice, governance, persistence guarantees, observability, and release verification.

## 4. Detailed functionality inventory

### 4.1 Local launch and installation

**Implemented in repository**

- `python3 run_studio.py` starts the local Studio from a source checkout.
- Startup builds/loads the native shared library through the GraphCore Python wrapper's library discovery path.
- The server binds to loopback (`127.0.0.1`) and prints the actual URL. It prefers port 8787 and falls back to an available local port if that port is already occupied.
- CLI options include `--port`, `--data`, and repeatable `--plugin` arguments.
- `graphcore-studio` is the installed command exposed by package metadata. The distribution name is `graphcore-studio`; the Python import is `graphcore`.
- PyPI dependencies include OpenRouter SDK and Pydantic v2. Offline demo workflows do not need an API key or live model call.

**Product implications and constraints**

- Users must open the printed `http://127.0.0.1:<port>/` URL. Opening `studio/web/index.html` directly using a `file://` URL bypasses the HTTP API and breaks absolute asset and API paths; the HTML file is not a supported standalone app.
- A source install needs a C++17 compiler and CMake. Prebuilt wheels are intended to avoid this for supported platforms/architectures; the repository release notes say hosted wheel artifacts still require verification before being considered fully verified.
- Local launch is single-user and machine-bound. No account, remote workspace, hosted control plane, or team installation flow is present.
- The current working-tree knowledge feature adds a module to source packaging metadata, but that change is not in the published 0.2.2 artifact unless a new release is built and uploaded.

### 4.2 Workflow canvas and authoring

**Implemented in repository**

- A plain HTML/CSS/JavaScript canvas renders nodes and connections without Node.js, a frontend framework, or a bundling step.
- Users can click a node in the palette or drag it onto the canvas. Nodes can be dragged to arrange the graph.
- Node connection can be made through output/input ports or through destination selectors in the inspector.
- Condition nodes have separate true and false outputs. Other executable nodes have a next output. Output nodes terminate a path.
- Canvas supports pan, zoom, fit-to-workflow, node search, selection, active execution highlights, and an empty-canvas state.
- The editor supports keyboard undo/redo (`Ctrl/Cmd+Z`, and the redo control), node deletion (Delete/Backspace), and Escape to cancel a connection.
- The **Clear** button confirms before removing nodes and edges and records an undo state.
- The editor shows workflow name, draft/save status, graph node/edge counts, engine status, and whether the current graph uses live model calls or only offline demo nodes.
- The inspector edits node labels, node configs, prompts, routes, output fields, and structured-output schema fields.
- The JSON editor can display, edit, and apply a workflow document. Users can import a JSON file and export a JSON workflow.
- Browser `localStorage` stores the current draft, so a page reload on the same browser can restore the editor draft.

**Limits**

- The browser draft is separate from server-saved workflows and run checkpoints. It is local to that browser profile and is not collaborative or synchronized.
- Canvas is a graph editor, not a free-form workflow notation: node types and configuration are the supported extension points.
- Workflows are versioned JSON (`graphcore.studio.v1`). No migration/version-upgrade UI is documented for future schema versions.
- UI validation and backend validation are not the same as static type-checking or guarantees that all runtime provider responses will match a downstream schema.
- Source includes a 100-node/300-edge validation ceiling. This is a product safety cap, not a demonstrated scale target.

### 4.3 Node catalog and behavior

The visual palette exposes the following node kinds. Graph nodes are executed sequentially along the selected route; the graph does not fan out concurrently.

#### Input

- Exactly one Input node is required by backend workflow validation.
- Initial state is supplied as a JSON object in the Input panel below the canvas.
- Other nodes can reference top-level and nested state paths, e.g. `{{request}}` or `{{request.topic}}`.
- The input node does not create an additional state update; the initial input object is the graph state.

#### Agent

- Conceptually represents a prompt-driven agent step and can be connected sequentially to later steps.
- Supports the offline deterministic response fixture or a live OpenRouter model.
- Configures provider, model ID/named model variable, messages, temperature, token limit, timeout, reasoning effort, JSON-output mode, and output state key where supported by the inspector.
- Despite the “agent” label, this release does not provide an autonomous tool-calling loop inside an Agent node. Agent-to-agent handoffs are ordinary sequential graph steps.

#### Chat Model

- Calls a chat model once and writes its returned content to a selected state key.
- Supports system, user, and assistant message roles. Message text can include workflow-state variable placeholders.
- Supports named OpenRouter model variables, literal model IDs, temperature, max completion tokens, timeout, reasoning effort, and JSON mode.
- A response with no visible answer receives one retry with an expanded token budget and `reasoning_effort=none`; a second empty response becomes an actionable workflow error.
- Calls are non-streaming. There is no provider-independent normalized model catalog or live model picker sourced from all providers.

#### Condition

- Compares a named top-level state field to a configured JSON expected value.
- Routes to exactly one true target or one false target. Both routes must be connected once.
- Comparison runs in C++ using canonical JSON values; type differences matter (`true`, `"true"`, and `1` are distinct).
- Cycles are permitted, but the run has a maximum-step limit.

#### Python tool

- Calls a named registered Python function with `(value, config)` and expects a JSON-compatible return value.
- Built-in tools: `word_count`, `uppercase`, `parse_json`, and `keywords`.
- A developer can register additional functions by loading a trusted local plugin at startup with `--plugin path/to/plugin.py`.
- Arbitrary executable code cannot be embedded directly in a workflow JSON document.
- Plugins run in the Studio process with the current OS user's privileges; there is no sandbox.

#### Structured output

- Accepts a JSON object (or JSON text), validates a flat list of named fields, and writes the validated value to state.
- Field types: string, integer, number, boolean, object, and array. Fields can be required or optional.
- Built-in strict validation is available offline. Optional Pydantic mode creates a Pydantic v2 model from the configured field list.
- Extra fields are rejected; missing required fields and type mismatches fail the node.
- Nested JSON Schema composition, unions, custom validators, constrained values, field descriptions, and secret types are not exposed in the UI.

#### Human approval

- Renders a configurable prompt from current state and suspends the run, persisting a checkpoint.
- The UI displays a JSON response input and lets the user resume. The response is written to the configured output key.
- The graph can continue to a later condition or output after approval.
- This is an interactive local approval pause, not a multi-approver policy, role-based approval workflow, notification service, or audit-grade sign-off.

#### Output

- Renders a final text template using current workflow state and writes it to the `output` key.
- Ends the graph path. Users can inspect the final result and full final state.
- The output template supports nested state references; non-string values are JSON serialized when inserted.

#### Document retrieval — current working-tree addition

- A new **Knowledge library** UI manages text files in the local Studio data directory.
- Supported extensions are `.txt`, `.md`, `.csv`, and `.json`; the UI/server caps documents at 1 MiB each, 10 MiB total, and 100 documents.
- A new Document retrieval node accepts a state field as the query, a top-k count from 1 to 10, and an output key.
- Text is split into bounded overlapping passages and ranked locally with BM25 keyword matching. Returned records include passage text, source filename, source document ID, chunk index, and score.
- A downstream prompt can insert `{{context.results}}` (or the configured output key) to provide retrieved passages to a model.
- This feature uses no embedding model or external vector store; it is lexical retrieval only. PDF/Office extraction, semantic embeddings, chunking controls, collections, metadata filtering, citations with page/section anchors, and permission-aware retrieval are not implemented.
- This remains an uncommitted working-tree addition. On macOS ARM64, unit tests and a local HTTP upload → retrieval workflow run → removal test pass. A fresh wheel and source distribution build include the module, and the installed wheel smoke test passes. Browser interaction, Linux/Windows builds, and a new PyPI release remain unverified.

### 4.4 Prompt variables and workflow state

- Message and output templates replace `{{field}}` and dotted paths such as `{{record.summary}}` with values from current state.
- Object, list, and numeric values are inserted as JSON text; strings are inserted directly.
- The model editor offers an **Insert variable** selector populated from workflow input fields and earlier node outputs; schema outputs also expose their configured field names.
- The backend lookup fails the node when a referenced state field is absent. There is no current optional/default syntax, expression language, template escaping syntax, or typed variable binding UI.
- State is a JSON object at the Python boundary and a map of JSON-encoded strings inside the native runtime/C ABI wire representation.

### 4.5 Model integrations and configuration

- Model integrations UI stores named variables such as `model1 → deepseek/deepseek-v4-pro-0813`; a node refers to a saved entry as `$model1`.
- Multiple named model IDs can be configured and used across different nodes in the same workflow.
- OpenRouter is the only implemented live provider. Adding another string in the provider selector is not supported by the backend.
- Provider credentials and custom environment entries can be configured through the UI and written to the local `.env` file. The server loads these values before model requests. Existing values are write-only in the UI; leaving a saved secret blank preserves it.
- Environment variable names are validated and dangerous process-control variables are blocked. Values are single-line text with a length cap. `.env` permissions are restricted where supported; the values remain local plaintext at rest.
- OpenRouter requests support role messages, non-streaming completion, temperature, completion token cap, timeout, reasoning effort, and JSON-object response mode.
- Provider errors are surfaced to the run and API; the API key is removed from error text before it is stored/displayed.
- No automatic provider failover, user-configurable routing policies, local model runtime, per-model credentials, cost estimator, token/cost accounting dashboard, global LLM-call budget, streaming tokens, prompt version registry, or credential vault is present.

### 4.6 Workflow validation and persistence

- Backend validates format, node IDs, node types, configs, model references, schema definitions, graph connections, reachability, output paths, condition routes, and size/step limits before starting a run.
- Exactly one input is required; at least one output is required. Every node must be reachable from input and have a path to output.
- Workflow documents are saved locally as JSON. Drafts can be imported/exported as JSON independently of server saves.
- Each run captures a copy of the workflow, input object, and named model registry as it existed at start. An SHA-256 workflow hash is passed as the native graph version for checkpoint compatibility.
- Run records include status, elapsed duration, full state, prompt/error details, and execution events. The server loads up to the latest 100 stored run metadata files on startup.
- The C++ file checkpoint is replaced using a sibling temporary file and atomic rename. It stores graph version, next node, step count, interruption metadata, and state.
- Resume continues from a suspended approval. Recover re-runs from the most recently committed node checkpoint after an interrupted process.

**Persistence caveats**

- Checkpoint files do not provide database transactions, encryption, a documented `fsync` guarantee, cross-process locking, multi-writer support, retention/compaction policy, or a managed backup/restore flow.
- Recovery is at-least-once for external side effects: a callback could have performed an effect before a crash but before the next checkpoint, then execute again on recovery. Integrations should use idempotency keys.
- Run events can persist model prompts and outputs; large runs can consume disk. There is no trace-redaction UI or export bundle.
- User documents and `.env` values are not encrypted at rest.

### 4.7 Run operations and execution visibility

- Users can submit JSON input, start a run, see current status, view final output/state, and inspect an event trace.
- Run statuses include queued, running, cancelling, completed, failed, suspended, recoverable, and cancelled.
- The canvas highlights running/completed/failed/interrupted nodes based on the run event log.
- Up to four runs can be active across the local server's worker pool; each graph executes its own nodes sequentially.
- A run can be cancelled cooperatively between callbacks. Blocking model/library calls cannot be forcibly stopped by this mechanism.
- Run history lists recent runs with name, timestamp, duration, and status. Selecting a prior run restores its workflow and its status/output view.
- Users can recover from a checkpoint after restart if a valid checkpoint exists.
- There are no metrics export, structured log streaming, OpenTelemetry tracing, per-step token/cost measurement, run comparison, replay diff, or performance benchmark view in the product UI.

### 4.8 Local HTTP server and security boundaries

- Uses Python's standard-library HTTP server, binds only to `127.0.0.1`, checks the Host, checks browser Origin for writes, issues a per-launch token for state-changing requests, disables cache, and serves a restrictive Content Security Policy.
- Request sizes are capped. Workflow IDs and document IDs are constrained before use in local paths.
- Main routes cover bootstrap/static assets, environment/model configuration, document list/add/remove, workflow list/save, workflow validation, run start/list/detail, and run resume/recover/cancel.
- This is designed for a local browser on the same machine. It is not intended to be proxied or exposed on a public interface.
- Loopback binding and a session token do not sandbox trusted Python plugins, model responses, or OS access. A malicious or compromised local plugin can act with the user's permissions. Retrieved content may contain prompt injection; models must be instructed and the workflow designed to treat document text as untrusted data.
- There is no login, RBAC, tenant isolation, organization policy, audit retention control, or remote access management.

### 4.9 Python SDK

The `graphcore` package wraps the C ABI using `ctypes` and exposes:

- `Graph(version)` to create a graph instance and load the shared library.
- `add_node(name, function, retries=0)` to register sync Python callbacks or supported coroutine callbacks.
- `add_condition(name, field, expected, yes, no)` for native equality routing.
- `add_edge(source, target)` and `set_entry(name)` for topology.
- `observe(callback)` for native node lifecycle events; observer callback exceptions are isolated.
- `invoke(state, checkpoint=None, max_steps=100)` for synchronous execution.
- `ainvoke(...)` for async Python callback execution with the coroutine bridged to an executor thread.
- `resume(...)` and `aresume(...)` for suspended graphs; `recover(...)` and `arecover(...)` for checkpoint recovery.
- `inspect_checkpoint(path)` to read saved state without advancing the graph.
- `cancel()` for cooperative run cancellation and `close()` / context-manager support for native handle lifecycle.
- Data structures `Context`, `Update`, `Interrupt`, `Result`, plus `GraphCoreError`.

SDK constraints include one active invocation at a time per Graph object, JSON-compatible state and return values, explicit lifetime management, a required native shared library, sequential execution, and cooperative cancellation. The async API shields a running native operation rather than abandoning it if the awaiting coroutine is cancelled.

### 4.10 Native C++ API and runtime

- Public C++17 API: `GraphBuilder`, `Graph`, `Runtime`, `NodeResult`, `NodeOptions`, `RunOptions`, `Snapshot`, `Context`, and abstract `CheckpointStore` with `FileCheckpoint` implementation.
- `GraphBuilder` adds nodes, declares each node's target list, chooses an entry node, and compiles a graph after basic topology/version checks.
- Node callbacks read a `State` snapshot and return updates, optional next route, or a suspension prompt.
- `Runtime::invoke` executes from initial state. `Runtime::resume` loads a checkpoint, validates graph version, and resumes a suspended or recoverable execution.
- Scheduler enforces declared routes, max steps, cancellation checks between callbacks, update commits, checkpoint commits, and observer events.
- Condition node support is exposed through the C ABI as equality comparison with true/false routes.
- C API exposes create/destroy, add callback node, add equality condition, connect, set entry, run, inspect checkpoint, cancellation, observer, result/status getters, and callback reply helpers.
- The native state representation maps string keys to JSON-encoded strings. The cross-language wire format uses hex-encoded UTF-8 keys and JSON values to avoid delimiter/NUL ambiguity.
- Native runtime callbacks are not parallelized. Each graph runs one node at a time.

## 5. User journeys supported today

### Offline workflow trial

1. Launch Studio through the CLI and open its printed local HTTP URL.
2. Choose an offline template or onboarding action.
3. Edit Input JSON and run.
4. Inspect output, state, per-node trace, or run history.

**Expected product outcome:** user can see and understand the canvas/run loop without credentials or model spend.

### Live multi-model workflow

1. Configure `OPENROUTER_API_KEY` under Model integrations.
2. Add named model IDs, for example `model1` and `model2`.
3. Assign different named models to Chat Model/Agent nodes.
4. Compose role messages, insert state variables, optionally request JSON mode, and validate structured output.
5. Run and inspect result/error and duration.

**Expected product outcome:** sequential graph steps may call different OpenRouter model IDs. Provider portability, budget control, and streaming are not implied.

### Human review workflow

1. Connect a node to Human approval.
2. The run renders a state-aware review prompt and pauses with a persisted checkpoint.
3. A person enters a JSON response and resumes.
4. Downstream nodes use the response field.

**Expected product outcome:** a local manual review gate. It is not a managed approval process with identity, assignment, notification, or tamper-evident audit.

### Python library integration

1. Write a Python module that registers a callable.
2. Start Studio with `--plugin`.
3. Select the tool in a Python Tool node and connect it in the graph.

**Expected product outcome:** existing Python code can be called. Plugin trust is equivalent to running that code directly under the current user account.

### Local document Q&A (working-tree addition)

1. Add supported text documents in Knowledge library.
2. Connect Input → Document retrieval → Chat Model → Output.
3. Set the retrieval query field, then reference the retrieval output's `.results` in the prompt.
4. Inspect retrieved source names and passages in state/trace/output.

**Expected product outcome:** keyword-grounded prompt construction with local source labels. It is not yet semantic RAG, a permission-aware corpus service, or an end-to-end verified release feature.

## 6. Product readiness and key gaps

### Prototype-ready strengths

- Simple, local installation model and offline demo path.
- Clear C++ scheduler/Python integration boundary.
- Graph validation and explicit per-node configuration.
- Local state, run history, approval interrupts, and checkpoint recovery.
- Extensibility through Python callables and public C++/Python APIs.
- Multiple named model IDs available across nodes through OpenRouter.

### Enterprise adoption blockers

1. **Reliability and durability:** no database backend, retention policy, integrity/migration plan, cross-process concurrency, strong power-loss durability, or distributed workers.
2. **Execution semantics:** no persisted fan-out/join supersteps, parallel node execution, reducers, or robust cancellation/deadlines for blocking integrations.
3. **Governance/security:** no users/roles, organization policy, tenant isolation, sandboxing, secret vault, approval identity, redaction, or audit controls.
4. **Model platform:** one provider, non-streaming requests, no failover, call/cost budget, token accounting, or model evaluation workflow.
5. **Data/RAG:** current addition is BM25 over a small local text corpus; no embeddings, vector store, PDF extraction, access filtering, ingestion pipeline, or citation validation.
6. **Operational visibility:** no OpenTelemetry, production metrics, alerting, run comparisons, or supported support bundle.
7. **Product polish and accessibility:** editor supports core interaction but needs systematic keyboard/screen-reader and responsive QA, error recovery, discoverability, and first-use guidance validation.
8. **Release confidence:** cross-platform wheel workflow and current source changes need build, package-content, install, and smoke verification before a new public release.

## 7. Recommended product decisions for PM review

These are decision prompts, not committed roadmap scope.

- Is the product's initial buyer an individual Python/C++ developer, an internal platform team, or a visual no-code user? These personas have different expectations for authoring, governance, and deployment.
- Is the primary differentiator visual authoring, local privacy, Python extensibility, native scheduler performance, or a combined story? Measure the claim that matters instead of relying on language choice as a proxy.
- Should the product remain desktop/local-first, or is a team-hosted control plane an explicit objective? This affects auth, data tenancy, secrets, concurrency, and operations.
- Is OpenRouter the deliberate v1 provider, or must provider abstraction and at least one alternative be a launch requirement?
- Should enterprise RAG be a first-class product area? If yes, define source ingestion, supported formats, permission boundaries, retrieval quality, evaluation, citations, and index lifecycle before expanding UI scope.
- What does a “successful workflow run” mean for a product metric: completed, correct output, schema-valid, cited, within cost/latency budget, or user-approved?
- What guarantees are required for retries, duplicate side effects, human approvals, checkpoint durability, run retention, and reproducibility?
- Which workflow/version compatibility promises should users receive when saved JSON and native checkpoint formats evolve?
- Which plugins are trusted, how are they installed/reviewed, and should plugin execution be sandboxed or isolated in a separate process?
- What minimum release gates are required for PyPI: all supported wheel architectures, dependency matrix, security review, smoke install, demo workflow, and artifact provenance?

## 8. Suggested product metrics

Instrument locally/with explicit user consent if telemetry is ever introduced; the current application has no telemetry system.

- Activation: time from launch to first successful offline run; share of new users completing a template run.
- Authoring: time to build/save a valid workflow; node types used; validation failures per workflow.
- Run quality: completion/failure/suspension/recovery rates; median and p95 run duration by workflow shape.
- Model experience: visible empty-response rate, provider errors, token/cost per run when available, schema-valid response rate.
- RAG quality: retrieval hit rate, source coverage, grounded answer acceptance, citation correctness, and user edits after retrieval.
- Reliability: duplicate side-effect incidents, checkpoint recovery success, cancellation-to-stop latency, corrupted/missing run records.
- Adoption: repeat use, exported workflows, plugin integrations, package install success by Python/OS/compiler combination.
- Trust: number of workflows using secrets safely, user understanding of local data location and plugin permissions, approval completion and audit completeness.

## 9. Current scope matrix

| Capability | Current assessment | User-facing constraint |
|---|---|---|
| Visual graph editing | Implemented | Single graph, 100-node limit, no collaborative editing |
| Sequential graph runtime | Implemented | One node at a time; no parallel fan-out/join |
| Branching and cycles | Implemented | Equality conditions; bounded by run step limit |
| Live model access | Implemented, limited | OpenRouter only; no streaming or failover |
| Multiple named models | Implemented | Multiple OpenRouter model IDs; not multi-provider |
| Structured output | Implemented, limited | Flat configured field list; strict basic types |
| Human approval | Implemented | Local interactive pause/resume only |
| Python tools | Implemented | Trusted plugins run with current-user privileges |
| Checkpoint/recovery | Implemented, limited | Local files; at-least-once side effects; no DB guarantee |
| Local text retrieval | Current working-tree addition | Small local BM25 corpus; no semantic search/PDF |
| Team/workspace management | Not available | No accounts, RBAC, or shared workspace |
| Enterprise operations | Not available | No distributed workers, SSO, audit policy, or metrics export |
| Cross-platform package | Intended, verification pending | Confirm wheel build and install per supported platform |

## 10. Source map for product and engineering review

- `studio/web/index.html`, `studio/web/app.js`, `studio/web/style.css`: visual editor and user interactions.
- `studio/engine.py`: workflow validation, model integration, Python tool dispatch, schema behavior, graph compilation.
- `studio/server.py`: local HTTP API, configuration, plugin loading, run manager, persistence, recovery, security checks.
- `studio/knowledge.py`: current working-tree local text ingestion and BM25 search addition.
- `python/graphcore/__init__.py`: Python SDK, C ABI binding, async callback bridge, graph lifecycle.
- `include/graphcore/graphcore.hpp`, `src/graphcore.cpp`: native runtime API, sequential scheduler, state transitions, file checkpoints.
- `include/graphcore/c_api.h`, `src/c_api.cpp`: C ABI boundary between Python and C++.
- `studio/templates/`: five starter templates.
- `examples/`: workflow JSON and Python/C++ examples.
- `docs/SEMANTICS.md`: run and recovery contract.
- `docs/ARCHITECTURE.md`: architecture and extension points.
- `docs/ROADMAP.md`: known gaps and planned release gates.
- `pyproject.toml`: package metadata, dependencies, command, wheel and source inclusion.

## 11. Review note

This catalog was assembled from repository source and documentation. The retrieval path has local macOS unit/HTTP/package smoke coverage, but not browser-level or cross-platform release verification. The addition and other uncommitted working-tree changes must be distinguished from the PyPI 0.2.2 package. Before using this file as external product collateral, reconcile it with the exact release tag/artifacts, run supported-platform installation and smoke checks, and update the status labels.
