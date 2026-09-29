#!/usr/bin/env python3
"""One-command local launch: builds the native library if needed, then serves Studio."""
from pathlib import Path
import os
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def build_native():
    system = platform.system()
    filename = "graphcore.dll" if system == "Windows" else "libgraphcore.dylib" if system == "Darwin" else "libgraphcore.so"
    output = ROOT / "build" / filename
    sources = [ROOT / "src/graphcore.cpp", ROOT / "src/c_api.cpp"]
    tracked = sources + list((ROOT / "include/graphcore").glob('*'))
    if output.exists() and output.stat().st_mtime >= max(p.stat().st_mtime for p in tracked): return
    compiler = shlex.split(os.environ["CXX"]) if "CXX" in os.environ else []
    if not compiler:
        found = next((shutil.which(c) for c in ("c++", "g++", "clang++", "cl") if shutil.which(c)), None)
        if not found:
            raise SystemExit("A C++17 compiler is required. Install your platform's C++ toolchain, then rerun. On Windows use a Visual Studio Developer terminal.")
        compiler = [found]
    output.parent.mkdir(exist_ok=True)
    if Path(compiler[0]).stem.lower() == "cl":
        command = compiler + ["/nologo", "/std:c++17", "/EHsc", "/O2", "/LD", "/DGRAPHCORE_BUILD_SHARED", "/Iinclude", "/Fobuild/", "src/graphcore.cpp", "src/c_api.cpp", "/Fe:"+str(output), "/link", "/IMPLIB:build/graphcore_c.lib"]
    else:
        command = compiler + ["-std=c++17", "-O2", "-fPIC", "-dynamiclib" if system=="Darwin" else "-shared", "-DGRAPHCORE_BUILD_SHARED", "-Iinclude", "src/graphcore.cpp", "src/c_api.cpp", "-o", str(output)]
    print("Building the C++ engine…", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)

if __name__ == "__main__":
    build_native()
    sys.path.insert(0, str(ROOT))
    from studio.server import main
    main()
