#!/bin/sh
# Offline build for macOS/Linux. Run from any working directory.
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
CXX=${CXX:-c++}
"$CXX" -std=c++17 -O2 -Wall -Wextra -Wpedantic -Iinclude src/graphcore.cpp tests/core_tests.cpp -o build/graphcore_tests
"$CXX" -std=c++17 -O2 -Wall -Wextra -Wpedantic -Iinclude src/graphcore.cpp examples/approval.cpp -o build/graphcore_demo
case "$(uname -s)" in
  Darwin) "$CXX" -std=c++17 -O2 -fPIC -dynamiclib -DGRAPHCORE_BUILD_SHARED -Iinclude src/graphcore.cpp src/c_api.cpp -o build/libgraphcore.dylib ;;
  *) "$CXX" -std=c++17 -O2 -fPIC -shared -DGRAPHCORE_BUILD_SHARED -Iinclude src/graphcore.cpp src/c_api.cpp -o build/libgraphcore.so ;;
esac
./build/graphcore_tests
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH=python python3 tests/test_python.py
fi
