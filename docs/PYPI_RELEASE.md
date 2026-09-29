# PyPI release checklist

The distribution name is `graphcore-studio`; the Python import is `graphcore`. The shorter PyPI name `graphcore` is already registered by another project. Recheck `graphcore-studio` availability at upload time. Keep the version synchronized in `pyproject.toml`, `CMakeLists.txt`, and `python/graphcore/__init__.py`.

## Build and validate locally

Use Python 3.9 or newer, a C++17 compiler, and a working network connection for isolated build dependencies:

```bash
python -m pip install --upgrade build twine
python -m build --sdist --wheel
python -m twine check dist/graphcore_studio-*.whl dist/graphcore_studio-*.tar.gz
```

The source archive builds a native library at install time. Wheels contain the C++ shared library and Studio assets. `.github/workflows/wheels.yml` builds and tests CPython 3.9–3.13 wheels for Linux x86-64/ARM64, Windows x86-64, and macOS x86-64/ARM64. Run it manually from GitHub Actions or push a `v*` tag. The `graphcore-studio-distributions` artifact contains the combined wheels and source archive after Twine validation. Download those exact files for TestPyPI and release.

Never upload old `*-source.zip` files from `dist/`. Upload only the `.whl` and `.tar.gz` artifacts emitted by the build command. Inspect the archives before release: `studio/data/` is intentionally excluded because it may contain local workflows, run history, and secrets.

## TestPyPI first

Download the `graphcore-studio-distributions` artifact from a successful workflow run, create a TestPyPI project and API token, then upload the exact validated artifacts:

```bash
python -m twine upload --repository testpypi dist/*.whl dist/*.tar.gz
```

Install and test from a clean environment against TestPyPI before publishing to PyPI. Avoid pasting API tokens into the repository or chat; configure them through Twine's secure prompt or a protected environment variable.

## Publish

Confirm the package name is still available, the GitHub repository and release tag are correct, and the final artifacts have passed CI. Then publish those same tested artifacts:

```bash
python -m twine upload dist/*.whl dist/*.tar.gz
```

PyPI does not allow replacing files for an existing version. Increment the version in both metadata files for every subsequent release.
