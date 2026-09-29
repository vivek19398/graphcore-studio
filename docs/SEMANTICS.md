# Studio and execution semantics

## Design format

A workflow uses the versioned JSON format `graphcore.studio.v1`. Nodes have stable IDs, an editor position, a type, a label, and config. Edges name a source, target and output port. The editor saves this document separately from native run checkpoints.

The server rejects invalid documents before execution: IDs must be unique, there is one Input, branches must have exactly one true and false route, every executable node must have a target, and every node must be reachable from Input and able to reach Output. Conditional nodes can form cycles; the run-level step cap prevents accidental endless loops.

The graph hash pins each run to the exact workflow document it started with. Saving a later edit does not rewrite a past run. Python libraries are looked up by registered tool name; serialized workflow JSON never contains executable code.

## Execution split

The C++17 runtime owns sequential scheduling, node transitions, direct equality conditions, step limits, cancellation checks between callbacks and file-checkpoint commits. Python executes the local web API, model requests, registered integrations, demo fixtures and Pydantic validation. A Python callback crosses the C ABI and returns its update to the C++ scheduler before the next node runs.

A **demo model node uses a deterministic response template, not a model**. Select OpenRouter on a Chat Model or Agent node to make a request through the official OpenRouter Python SDK. The API key is read from the Studio process environment, which loads the local `.env` file on startup. The initial adapter performs non-streaming chat completions; it supports role-tagged messages, temperature, token limit, and JSON output mode.

OpenRouter JSON mode requests a JSON object; the next Structured output node can validate its shape and values. Built-in validation supports string, integer, number, boolean, object and array fields with strict primitive types. The standard PyPI install includes Pydantic v2, which adds Pydantic model validation to the same field list; custom Python validators are not configured through this UI yet.

## Native step commit

1. Check cancellation and the cumulative step limit.
2. Invoke the scheduled node against the current state snapshot.
3. For Agent/Tool/Schema/Approval/Output nodes, execute the Python handler; for Condition, compare its JSON-encoded value in C++ and pick the declared true/false edge.
4. Validate the selected route.
5. Apply the node update and checkpoint the new state and next node.
6. Publish completion and schedule the next node.

A failed node or undeclared route leaves the last checkpoint intact. Checkpoint storage failures stop the run. Observer exceptions cannot change execution. Equality conditions compare JSON representations (including types): `true` differs from `"true"` and from `1`.

The interactive engine is single-node-at-a-time. Multiple browser runs may execute in separate worker threads (up to four simultaneously), but each workflow's nodes run in sequence. Fan-out nodes do not run concurrently in this release.

## Interrupt, recovery, cancellation

Approval saves a file checkpoint containing the current state, interrupted node, and prompt. Resume restarts that node with the supplied response. A server restart inspects the last checkpoint; it restores approval as pending if the saved step was an interrupt, and otherwise offers recovery from the saved node.

Recovery restarts the node named by the most recent checkpoint. If that node made an external change and crashed before the next checkpoint, the action may run twice. Delivery is at least once across recovery; exactly-once side effects cannot be guaranteed. Use external idempotency keys or reconcile uncertain results.

Cancellation takes effect between Python/C++ node calls. It cannot forcibly stop a blocking library call or interrupt an in-progress network request. Closing the server requests cancellation and waits for active worker threads to finish; terminate the process only when willing to recover from its last checkpoint.

## Local persistence

Workflow JSON, run metadata and one checkpoint file per run live in the configured Studio data directory. Checkpoint replacement uses a sibling temp file and atomic rename on the local filesystem. There is no POSIX `fsync`, so sudden power loss can lose the last checkpoint. Multiple processes must not share a data directory. Files are not encrypted; use local OS account permissions.

Studio stores full event history in per-run metadata files. Large prompts/model outputs can therefore consume disk space. Request and workflow file sizes are capped; implement retention before using large production workloads.

## Local HTTP security

The server binds to `127.0.0.1`, validates the Host, issues a per-launch session token for writes, checks the browser Origin, caps request size, disables caching, and serves a restrictive Content Security Policy. It is designed for same-machine use. Do not expose the port through a proxy or configure public binding. Trusted plugin code runs with the current user's operating-system privileges.
