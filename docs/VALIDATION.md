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

## Follow-up local verification — 30 September 2026

The current uncommitted document-retrieval addition was checked on macOS ARM64 with the project Python 3.9.6 virtual environment:

- Retrieval unit tests: add/list/search/remove, invalid input handling, and a retrieval node executed through the native graph: passed.
- Workflow and Python SDK suites: 32 tests passed, including Pydantic v2.
- Local HTTP integration suite: 7 tests passed, including document upload/list/remove and an HTTP-started retrieval workflow that returned its source passage.
- Fresh Release CMake build: passed; CTest 2/2 passed.
- Fresh sdist and macOS ARM64 wheel builds: passed. Wheel uses the configured `macOS 11` deployment target, passes Twine checks, and contains the retrieval module, UI assets, and native library.
- Clean temporary-environment wheel smoke: native graph invocation, retrieval-module import, packaged UI asset presence, and `graphcore-studio --help`: passed. Rebuilding a wheel from the sdist also passed.

These checks do not include browser-level visual interaction or remote Linux/Windows CI. The locally built artifact still reports version 0.2.2, which is already released; do not upload it. Bump and synchronize package versions before preparing a new release. No live OpenRouter call or performance benchmark was run.

## October 2: local typed CSV increment

- 35 table/knowledge/compiler/Python tests passed in the project environment.
- 8 HTTP tests passed, including CSV import, preview, reference listing and native data-summary workflow completion.
- JavaScript syntax check passed using bundled Node.js.
- No live model calls, external connector actions, cross-platform CI or PyPI publication were performed.

## October 3: CSV browser and precision verification

- Actual browser CSV import, preview, generated summary workflow and native execution passed with synthetic data in an isolated temporary workspace.
- Adaptive decimal precision regression and bounded numeric inputs passed; 36 unit/compiler/Python tests and 8 HTTP tests passed.
- Fresh macOS 11 ARM64 wheel and sdist build, archive inclusion and Twine checks passed. Version remains 0.2.2; these are development artifacts, not upload candidates.

## October 3: guided CSV import

- 37 unit/compiler/Python tests and 9 loopback HTTP tests passed, including bounded nonpersisting CSV inspection.
- Actual browser column selection, inline invalid-type feedback, correction and successful import passed.
- JavaScript syntax and diff checks passed. No cross-platform CI or release upload performed.
