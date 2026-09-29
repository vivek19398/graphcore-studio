"""Installed command-line entry point for GraphCore Studio."""
import os
from pathlib import Path


def main():
    os.environ.setdefault("GRAPHCORE_STUDIO_DATA", str(Path.home() / ".graphcore-studio"))
    from studio.server import main as serve
    serve()
