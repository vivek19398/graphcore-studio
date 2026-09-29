"""Dependency-free Python SDK for the GraphCore native runtime.

Build the shared library first and set GRAPHCORE_LIBRARY if it is outside build/.
State values are JSON encoded individually; Python objects stay out of checkpoints.
"""
import asyncio
import ctypes as C
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from dataclasses import dataclass, field
from typing import Optional

END = "__end__"
__version__ = "0.2.1"

class GraphCoreError(RuntimeError):
    pass

@dataclass
class Context:
    resumed: bool = False
    response: object = None

@dataclass
class Update:
    values: dict = field(default_factory=dict)
    next: Optional[str] = None

@dataclass
class Interrupt:
    prompt: str

@dataclass
class Result:
    state: dict
    suspended: bool
    prompt: str
    steps: int

_EVENT = C.CFUNCTYPE(None, C.c_char_p, C.c_char_p, C.c_void_p)
_CALLBACK = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_char_p, C.c_void_p, C.c_void_p)

def _text(value):
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Expected a string without NUL characters")
    return value.encode("utf-8")

def _dump(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True)

def _encode(state):
    return "".join(_text(k).hex() + ":" + _dump(v).encode().hex() + "\n"
                   for k, v in state.items()).encode()

def _decode(wire):
    result = {}
    for line in wire.decode().splitlines():
        key, value = line.split(":", 1)
        result[bytes.fromhex(key).decode()] = json.loads(bytes.fromhex(value).decode())
    return result

def _load():
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    name = ("" if sys.platform == "win32" else "lib") + "graphcore" + suffix
    root = Path(__file__).resolve().parents[2]
    candidates = [Path(os.environ["GRAPHCORE_LIBRARY"])] if "GRAPHCORE_LIBRARY" in os.environ else [
        Path(__file__).parent / name, root / "build" / name, root / "build" / "Release" / name]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise GraphCoreError("Native library missing. Build it first; see README or set GRAPHCORE_LIBRARY.")
    lib = C.CDLL(str(path))
    definitions = {
        "gc_cancel": ([C.c_void_p], None),
        "gc_set_observer": ([C.c_void_p, _EVENT, C.c_void_p], C.c_int),
        "gc_add_condition": ([C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p], C.c_int),
        "gc_create": ([C.c_char_p], C.c_void_p),
        "gc_destroy": ([C.c_void_p], None),
        "gc_error": ([C.c_void_p], C.c_char_p),
        "gc_add_node": ([C.c_void_p, C.c_char_p, _CALLBACK, C.c_void_p, C.c_uint], C.c_int),
        "gc_add_edge": ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_int),
        "gc_set_entry": ([C.c_void_p, C.c_char_p], C.c_int),
        "gc_run": ([C.c_void_p, C.c_char_p, C.c_char_p, C.c_int, C.c_char_p, C.c_size_t], C.c_int),
        "gc_inspect_checkpoint": ([C.c_void_p, C.c_char_p], C.c_int),
        "gc_result": ([C.c_void_p], C.c_char_p),
        "gc_prompt": ([C.c_void_p], C.c_char_p),
        "gc_suspended": ([C.c_void_p], C.c_int),
        "gc_steps": ([C.c_void_p], C.c_size_t),
        "gc_reply_update": ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_int),
        "gc_reply_next": ([C.c_void_p, C.c_char_p], C.c_int),
        "gc_reply_suspend": ([C.c_void_p, C.c_char_p], C.c_int),
        "gc_reply_error": ([C.c_void_p, C.c_char_p], C.c_int),
    }
    for name, (args, result) in definitions.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    return lib

class Graph:
    """Sequential durable graph. Use a separate Graph instance for concurrent runs.

    Python callbacks return a dict, Update, or Interrupt. Async callbacks require
    ainvoke/aresume. Explicitly close the graph or use it as a context manager.
    """
    def __init__(self, version="1"):
        self._lib = _load()
        self._handle = self._lib.gc_create(_text(version))
        if not self._handle:
            raise GraphCoreError("Cannot create graph")
        self._callbacks = []
        self._lock = threading.Lock()
        self._loop = None
        self._has_async = False
        self._observer = None
        self._lifecycle = threading.Lock()

    def _check(self, code):
        if code:
            raise GraphCoreError(self._lib.gc_error(self._handle).decode())

    def _enter(self):
        if not self._lock.acquire(blocking=False):
            raise GraphCoreError("Graph is in use; concurrent calls are unsupported")
        if not self._handle:
            self._lock.release()
            raise GraphCoreError("Graph is closed")

    def add_condition(self, name, field, expected, yes, no):
        """Compare canonical JSON values and select a route entirely in C++."""
        self._enter()
        try:
            self._check(self._lib.gc_add_condition(self._handle, _text(name), _text(field),
                        _text(_dump(expected)), _text(yes), _text(no)))
        finally:
            self._lock.release()
        return self

    def observe(self, callback):
        def emit(kind, node, user):
            try:
                callback(kind.decode(), node.decode())
            except Exception:
                pass
        self._enter()
        try:
            observer = _EVENT(emit)
            self._check(self._lib.gc_set_observer(self._handle, observer, None))
            self._observer = observer
        finally:
            self._lock.release()
        return self

    def cancel(self):
        """Cooperatively cancel; use a new Graph after cancellation."""
        with self._lifecycle:
            if self._handle:
                self._lib.gc_cancel(self._handle)

    def add_node(self, name, function, retries=0):
        if not callable(function):
            raise TypeError("Node must be callable")
        if not isinstance(retries, int) or not 0 <= retries <= 1000:
            raise ValueError("retries must be between 0 and 1000")
        is_async = inspect.iscoroutinefunction(function)
        def call(wire, resumed, response, reply, user):
            try:
                context = Context(bool(resumed), json.loads(response) if resumed else None)
                result = function(_decode(wire), context)
                if inspect.isawaitable(result):
                    if self._loop is None:
                        if inspect.iscoroutine(result):
                            result.close()
                        raise GraphCoreError("Async callbacks require ainvoke/aresume")
                    async def await_result():
                        return await result
                    result = asyncio.run_coroutine_threadsafe(await_result(), self._loop).result()
                if isinstance(result, Interrupt):
                    if self._lib.gc_reply_suspend(reply, _text(result.prompt)):
                        raise GraphCoreError("Cannot construct interrupt")
                else:
                    update = result if isinstance(result, Update) else Update(result)
                    if not isinstance(update.values, dict):
                        raise TypeError("Node must return dict, Update, or Interrupt")
                    for key, value in update.values.items():
                        if self._lib.gc_reply_update(reply, _text(key), _text(_dump(value))):
                            raise GraphCoreError("Cannot construct update")
                    if update.next is not None and self._lib.gc_reply_next(reply, _text(update.next)):
                        raise GraphCoreError("Cannot construct route")
                return 0
            except BaseException:
                self._lib.gc_reply_error(reply, traceback.format_exc().replace("\0", "\\0").encode())
                return -1
        callback = _CALLBACK(call)
        self._enter()
        try:
            self._check(self._lib.gc_add_node(self._handle, _text(name), callback, None, retries))
            self._callbacks.append(callback)
            self._has_async |= is_async
        finally:
            self._lock.release()
        return self

    def add_edge(self, source, target):
        self._enter()
        try:
            self._check(self._lib.gc_add_edge(self._handle, _text(source), _text(target)))
        finally:
            self._lock.release()
        return self

    def set_entry(self, name):
        self._enter()
        try:
            self._check(self._lib.gc_set_entry(self._handle, _text(name)))
        finally:
            self._lock.release()
        return self

    def _run(self, state, checkpoint, resume, response, max_steps):
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be positive")
        path = _text(os.fspath(checkpoint)) if checkpoint is not None else None
        reply = _text(_dump(response)) if response is not _MISSING else None
        self._check(self._lib.gc_run(self._handle, _encode(state), path, resume, reply, max_steps))
        return Result(_decode(self._lib.gc_result(self._handle)),
                      bool(self._lib.gc_suspended(self._handle)),
                      self._lib.gc_prompt(self._handle).decode(), self._lib.gc_steps(self._handle))

    def inspect_checkpoint(self, checkpoint):
        """Read saved state without executing callbacks or advancing the graph."""
        self._enter()
        try:
            self._check(self._lib.gc_inspect_checkpoint(self._handle, _text(os.fspath(checkpoint))))
            return Result(_decode(self._lib.gc_result(self._handle)),
                          bool(self._lib.gc_suspended(self._handle)),
                          self._lib.gc_prompt(self._handle).decode(), self._lib.gc_steps(self._handle))
        finally:
            self._lock.release()

    def invoke(self, state=None, *, checkpoint=None, max_steps=100):
        return self._sync(state or {}, checkpoint, False, _MISSING, max_steps)

    def resume(self, checkpoint, *, response=None, max_steps=100):
        return self._sync({}, checkpoint, True, response, max_steps)

    def recover(self, checkpoint, *, max_steps=100):
        return self._sync({}, checkpoint, True, _MISSING, max_steps)

    def _sync(self, *args):
        if self._has_async:
            raise GraphCoreError("Async callbacks require ainvoke/aresume")
        self._enter()
        try:
            return self._run(*args)
        finally:
            self._lock.release()

    async def ainvoke(self, state=None, *, checkpoint=None, max_steps=100):
        return await self._async(state or {}, checkpoint, False, _MISSING, max_steps)

    async def aresume(self, checkpoint, *, response=None, max_steps=100):
        return await self._async({}, checkpoint, True, response, max_steps)

    async def arecover(self, checkpoint, *, max_steps=100):
        return await self._async({}, checkpoint, True, _MISSING, max_steps)

    async def _async(self, *args):
        self._enter()
        self._loop = asyncio.get_running_loop()
        future = self._loop.run_in_executor(None, self._run, *args)
        # Native execution cannot be safely abandoned. Keep references and loop
        # association until it finishes, even if the awaiting caller cancels.
        def finish(_):
            self._loop = None
            self._lock.release()
            if not future.cancelled():
                future.exception()  # Retrieve errors if the caller was cancelled.
        future.add_done_callback(finish)
        return await asyncio.shield(future)

    def close(self):
        if not self._handle:
            return
        self._enter()
        try:
            with self._lifecycle:
                self._lib.gc_destroy(self._handle)
                self._handle = None
            self._callbacks.clear()
        finally:
            self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

_MISSING = object()
