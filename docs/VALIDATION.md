# Local validation

Validated on macOS ARM64 with Apple Clang 21 and Python 3.9.6 plus Pydantic 2.13.5.

- Compiler-only C++17 build and C ABI shared library: passed.
- Native runtime suite: 23 checks passed.
- Python bridge suite: 10 tests passed, including Python async callbacks, abrupt-process-exit recovery and restart of an approval checkpoint.
- Studio workflow suite: 17 tests passed, including all five templates, OpenRouter SDK request mapping and reasoning fallback, the Pydantic v2 engine, native routing, tool registration, graph pinning, and interrupted server recovery.
- Loopback HTTP suite: 5 integration tests passed, including OpenRouter-only provider discovery, workflow save/run/history, write-only `.env` settings, local session token checks, and cross-origin rejection.
- AddressSanitizer and UndefinedBehaviorSanitizer native suite: 23 checks passed.
- Browser integration: ran and resumed a two-agent approval workflow; ran Pydantic output validation; ran the supervisor and observed C++ routing to the technical specialist.
- Plain HTML/CSS/JS canvas opened locally with no Node.js or frontend dependencies.

PyPI packaging: source distribution and macOS ARM64 wheel built; `twine check` passed; the source archive rebuilt the wheel; installed-wheel smoke test passed for native execution, Studio assets, and CLI parsing. Local workflows, run history, and `.env` are excluded from both artifacts.

CI definitions for Linux, macOS and Windows have not run remotely. Only the local macOS ARM64 wheel has been built; the release workflow must run from the GitHub repository before its Windows and Linux wheels can be verified. No performance comparison, PyPI upload, or power-loss durability certification has been performed.
