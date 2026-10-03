#!/usr/bin/env python3
"""Local-only Studio server. No third-party web framework or frontend build needed."""
import argparse
import copy
import errno
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shlex
import tempfile
import sys
import threading
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
from studio.engine import compile_workflow, validate, TOOLS, KEY, pydantic_available, provider_availability, register_tool
from studio.knowledge import LocalKnowledge
from studio.tables import LocalTables

WEB = ROOT / "studio" / "web"
TEMPLATES = ROOT / "studio" / "templates"
ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
TERMINAL = {"completed", "failed", "cancelled", "suspended", "recoverable"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
ENV_BLOCKLIST = {"PATH", "PYTHONPATH", "PYTHONHOME", "HOME", "SHELL", "VIRTUAL_ENV",
                 "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH"}

def now(): return datetime.now(timezone.utc).isoformat()

def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)

def read_dotenv(path):
    values = {}
    try: lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError: return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("export "): line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not ENV_NAME.fullmatch(key) or key in ENV_BLOCKLIST: continue
        if value.startswith('"'):
            try:
                parsed, end = json.JSONDecoder().raw_decode(value)
                if isinstance(parsed, str): value = parsed
            except (ValueError, json.JSONDecodeError): pass
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1].replace("\\'", "'")
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values

def load_dotenv(path, override=False):
    """Load Studio's local .env file before model/provider construction."""
    values = read_dotenv(path)
    for key, value in values.items():
        if override or key not in os.environ: os.environ[key] = value
    return values

def write_dotenv(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# GraphCore Studio local model integrations\n" + "".join(
        key + "=" + json.dumps(value, ensure_ascii=False) + "\n" for key, value in sorted(values.items()))
    fd, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
    try:
        if hasattr(os, "fchmod"): os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output: output.write(body)
        os.replace(temporary, path)
        try: os.chmod(path, 0o600)
        except OSError: pass
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.env_path = self.root / ".env"
        self.base_environment = dict(os.environ)
        self.env_lock = threading.RLock()
        self.saved_environment = load_dotenv(self.env_path)
        self.models_path = self.root / "models.json"
        self.models = json.loads(self.models_path.read_text(encoding="utf-8")) if self.models_path.exists() else {}
        self.workflows = self.root / "workflows"; self.workflows.mkdir(exist_ok=True)
        self.runs = self.root / "runs"; self.runs.mkdir(exist_ok=True)
        self.tables = LocalTables(self.root / "tables")
        self.knowledge = LocalKnowledge(self.root / "knowledge")
        self.lock = threading.RLock()
        self.records = {}
        self.active = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="graphcore")
        self.slots = threading.BoundedSemaphore(4)
        for path in sorted(self.runs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                record = json.loads(path.read_text())
                if record["status"] in ("running", "queued", "cancelling"):
                    record["status"] = "recoverable" if self.checkpoint(record["id"]).exists() else "failed"
                    record["error"] = "Server stopped during execution. Recover from the last committed checkpoint."
                    if self.checkpoint(record["id"]).exists():
                        try:
                            from graphcore import Graph
                            with Graph() as reader:
                                saved = reader.inspect_checkpoint(self.checkpoint(record["id"]))
                            record["state"] = saved.state
                            if saved.suspended:
                                record.update(status="suspended", prompt=saved.prompt, error="")
                        except Exception:
                            pass
                self.records[record["id"]] = record
            except (ValueError, KeyError, OSError): pass

    def environment_status(self):
        stored = set(self.saved_environment)
        names = sorted(stored | {name for provider in provider_availability() for name in provider.get("env", [])})
        return [{"name": name, "configured": name in os.environ, "stored": name in stored}
                for name in names]

    def update_models(self, models):
        if not isinstance(models, dict) or len(models) > 50:
            raise ValueError("Configure up to 50 named models")
        for name, model in models.items():
            if not isinstance(name, str) or not KEY.fullmatch(name):
                raise ValueError("Model variable names must be simple identifiers")
            if not isinstance(model, str) or not model.strip() or len(model) > 200 or "/" not in model:
                raise ValueError("Each model needs an OpenRouter model ID such as openai/gpt-4o-mini")
        with self.lock:
            write_json(self.models_path, models)
            self.models = dict(models)
        return dict(self.models)

    def update_environment(self, values, remove):
        if not isinstance(values, dict) or not isinstance(remove, list):
            raise ValueError("Environment values must be an object and removals a list")
        if len(values) + len(remove) > 100: raise ValueError("Configure at most 100 environment variables")
        cleaned = {}
        for key, value in values.items():
            if not isinstance(key, str) or not ENV_NAME.fullmatch(key) or key in ENV_BLOCKLIST:
                raise ValueError("Invalid or reserved environment variable name")
            if not isinstance(value, str) or len(value) > 10000 or "\x00" in value or "\n" in value or "\r" in value:
                raise ValueError("Environment values must be single-line text up to 10000 characters")
            cleaned[key] = value
        if any(not isinstance(key, str) or not ENV_NAME.fullmatch(key) or key in ENV_BLOCKLIST for key in remove):
            raise ValueError("Invalid or reserved environment variable name to remove")
        with self.env_lock:
            result = dict(self.saved_environment)
            for key in remove:
                result.pop(key, None)
                if key in self.base_environment: os.environ[key] = self.base_environment[key]
                else: os.environ.pop(key, None)
            result.update(cleaned)
            write_dotenv(self.env_path, result)
            self.saved_environment = result
            os.environ.update(cleaned)
        return self.environment_status()

    def checkpoint(self, ident): return self.runs / (ident + ".checkpoint")

    def snapshot(self, ident):
        with self.lock:
            if ident not in self.records: raise ValueError("Run does not exist")
            return copy.deepcopy(self.records[ident])

    def history(self):
        with self.lock:
            return [{k: copy.deepcopy(r.get(k)) for k in ("id", "name", "status", "created", "duration_ms", "error")}
                    for r in sorted(self.records.values(), key=lambda r: r["created"], reverse=True)[:100]]

    def save_record(self, ident):
        write_json(self.runs / (ident + ".json"), self.records[ident])

    def start(self, workflow, inputs, max_steps=100):
        with self.lock: models = dict(self.models)
        errors = validate(workflow, models)
        if errors: raise ValueError("\n".join(errors))
        if not isinstance(inputs, dict): raise ValueError("Inputs must be a JSON object")
        if not isinstance(max_steps, int) or not 1 <= max_steps <= 1000: raise ValueError("Step limit must be 1–1000")
        if not self.slots.acquire(blocking=False): raise ValueError("Four runs are already active; wait for one to finish")
        ident = uuid.uuid4().hex
        record = {"id": ident, "name": workflow.get("name", "Untitled workflow"), "workflow": copy.deepcopy(workflow),
                  "inputs": copy.deepcopy(inputs), "models": models, "max_steps": max_steps, "created": now(), "status": "queued",
                  "events": [], "state": {}, "prompt": "", "error": "", "duration_ms": 0}
        try:
            with self.lock:
                self.records[ident] = record
                self.save_record(ident)
            self.pool.submit(self.execute, ident, "invoke", None)
        except BaseException:
            self.slots.release()
            raise
        return ident

    def continue_run(self, ident, action, response=None):
        with self.lock:
            record = self.records.get(ident)
            if not record: raise ValueError("Run does not exist")
            if action == "resume" and record["status"] != "suspended": raise ValueError("Run is not awaiting approval")
            if action == "recover" and record["status"] not in ("recoverable", "failed", "cancelled"):
                raise ValueError("Run is not recoverable")
            if not self.checkpoint(ident).exists(): raise ValueError("No checkpoint exists for this run")
            if not self.slots.acquire(blocking=False): raise ValueError("Four runs are already active")
            record["status"] = "queued"; record["error"] = ""
            self.save_record(ident)
            self.pool.submit(self.execute, ident, action, response)

    def cancel(self, ident):
        with self.lock:
            record = self.records.get(ident)
            if not record or record["status"] not in ("queued", "running", "cancelling"):
                raise ValueError("Run is not active")
            record["status"] = "cancelling"
            if ident in self.active: self.active[ident].cancel()
            self.save_record(ident)

    def execute(self, ident, action, response):
        start = time.monotonic()
        graph = None
        def emit(kind, **data):
            with self.lock:
                record = self.records[ident]
                record["events"].append({"sequence": len(record["events"]) + 1, "type": kind, "time": now(), **data})
                # Metadata follows a committed native checkpoint, never leads it.
                if kind in ("checkpoint.committed", "run.interrupted"):
                    self.save_record(ident)
        try:
            with self.lock:
                record = self.records[ident]
                workflow, inputs, budget = record["workflow"], record["inputs"], record["max_steps"]
            graph = compile_workflow(workflow, emit, record.get("models", {}),
                                     lambda library, query, top_k: self.knowledge.search(query, top_k),
                                     self.tables.summarize)
            with self.lock:
                self.active[ident] = graph
                if record["status"] == "cancelling": graph.cancel()
                else: record["status"] = "running"
            if action == "resume": result = graph.resume(str(self.checkpoint(ident)), response=response, max_steps=budget)
            elif action == "recover": result = graph.recover(str(self.checkpoint(ident)), max_steps=budget)
            else: result = graph.invoke(inputs, checkpoint=str(self.checkpoint(ident)), max_steps=budget)
            with self.lock:
                record.update(status="suspended" if result.suspended else "completed", state=result.state,
                              prompt=result.prompt, steps=result.steps)
        except Exception as error:
            with self.lock:
                record = self.records[ident]
                record["status"] = "cancelled" if record["status"] == "cancelling" else "failed"
                record["error"] = str(error)
        finally:
            with self.lock:
                self.active.pop(ident, None)
                record["duration_ms"] += round((time.monotonic() - start) * 1000)
                self.save_record(ident)
            if graph: graph.close()
            self.slots.release()

    def close(self):
        with self.lock:
            for graph in self.active.values(): graph.cancel()
        self.pool.shutdown(wait=True)

class Handler(BaseHTTPRequestHandler):
    server_version = "GraphCoreStudio/0.2"
    def log_message(self, format, *args): pass

    def allowed_host(self):
        return self.headers.get("Host") in ("127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port))

    def send(self, data, code=200, content_type="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if not isinstance(data, bytes) else data
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def do_GET(self):
        if not self.allowed_host(): return self.send({"error": "Invalid local Host"}, 403)
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/api/bootstrap":
                try:
                    from graphcore import Graph
                    with Graph(): pass
                    native, error = True, ""
                except Exception as failure: native, error = False, str(failure)
                templates = [json.loads(p.read_text()) for p in sorted(TEMPLATES.glob("*.json"))]
                return self.send({"csrf": self.server.token, "native": native, "native_error": error,
                    "pydantic": pydantic_available(), "providers": provider_availability(), "templates": templates,
                    "tools": [{"name": k, "description": v["description"]} for k,v in TOOLS.items()]})
            if path == "/api/settings/environment":
                return self.send({"variables": self.server.store.environment_status()})
            if path == "/api/settings/models":
                with self.server.store.lock: return self.send({"models": dict(self.server.store.models)})
            if path == "/api/tables":
                return self.send({"tables": self.server.store.tables.list()})
            if path.startswith("/api/tables/"):
                return self.send(self.server.store.tables.preview(path.rsplit("/", 1)[1]))
            if path == "/api/documents":
                return self.send({"documents": self.server.store.knowledge.list()})
            if path == "/api/workflows":
                with self.server.store.lock:
                    items = [json.loads(p.read_text()) for p in self.server.store.workflows.glob("*.json")]
                return self.send(items)
            if path == "/api/runs": return self.send(self.server.store.history())
            if path.startswith("/api/runs/"):
                ident = path.rsplit("/", 1)[1]
                if not ID.fullmatch(ident): raise ValueError("Invalid run ID")
                return self.send(self.server.store.snapshot(ident))
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path not in files: return self.send({"error": "Not found"}, 404)
            file = WEB / files[path]
            return self.send(file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] + "; charset=utf-8")
        except (ValueError, OSError) as error: self.send({"error": str(error)}, 400)

    def do_POST(self):
        if not self.allowed_host(): return self.send({"error": "Invalid local Host"}, 403)
        origin = self.headers.get("Origin")
        allowed = ("http://127.0.0.1:" + str(self.server.server_port), "http://localhost:" + str(self.server.server_port))
        if (origin is not None and origin not in allowed) or not secrets.compare_digest(self.headers.get("X-Studio-Token", ""), self.server.token):
            return self.send({"error": "Request must originate from the local Studio"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 5 * 1024 * 1024: raise ValueError("Request body must be 1 byte–5 MiB")
            body = json.loads(self.rfile.read(size), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
            if not isinstance(body, dict): raise ValueError("Request must be a JSON object")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/validate": return self.send({"errors": validate(body.get("workflow"), self.server.store.models)})
            if path == "/api/settings/environment":
                return self.send({"variables": self.server.store.update_environment(
                    body.get("values", {}), body.get("remove", []))})
            if path == "/api/settings/models":
                return self.send({"models": self.server.store.update_models(body.get("models"))})
            if path == "/api/tables/inspect":
                return self.send(self.server.store.tables.inspect(body.get("name"), body.get("text")))
            if path == "/api/tables":
                return self.send({"table": self.server.store.tables.add(body.get("name"), body.get("text"), body.get("types"))}, 201)
            if path == "/api/documents":
                return self.send({"document": self.server.store.knowledge.add(body.get("name"), body.get("text"))}, 201)
            if path == "/api/workflows":
                workflow = body.get("workflow")
                if not isinstance(workflow, dict) or workflow.get("format") != "graphcore.studio.v1": raise ValueError("Invalid workflow document")
                # Drafts may have incomplete connections; validate before running.
                ident = workflow.get("id")
                if not isinstance(ident, str) or not ID.fullmatch(ident): raise ValueError("Invalid workflow ID")
                with self.server.store.lock: write_json(self.server.store.workflows / (ident + ".json"), workflow)
                return self.send({"saved": True, "id": ident})
            if path == "/api/runs":
                ident = self.server.store.start(body.get("workflow"), body.get("inputs", {}), body.get("max_steps", 100))
                return self.send({"id": ident}, 202)
            match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_-]+)/(?P<action>resume|recover|cancel)", path)
            if match:
                ident, action = match.group(1), match.group("action")
                if action == "cancel": self.server.store.cancel(ident)
                else: self.server.store.continue_run(ident, action, body.get("response"))
                return self.send({"id": ident}, 202)
            return self.send({"error": "Not found"}, 404)
        except (ValueError, OSError, TypeError, KeyError) as error:
            self.send({"error": str(error)}, 400)

    def do_DELETE(self):
        if not self.allowed_host(): return self.send({"error": "Invalid local Host"}, 403)
        origin = self.headers.get("Origin")
        allowed = ("http://127.0.0.1:" + str(self.server.server_port), "http://localhost:" + str(self.server.server_port))
        if (origin is not None and origin not in allowed) or not secrets.compare_digest(self.headers.get("X-Studio-Token", ""), self.server.token):
            return self.send({"error": "Request must originate from the local Studio"}, 403)
        path = urllib.parse.urlsplit(self.path).path
        match = re.fullmatch(r"/api/documents/([a-f0-9]{32})", path)
        if not match: return self.send({"error": "Not found"}, 404)
        try:
            self.server.store.knowledge.remove(match.group(1))
            return self.send({"removed": True})
        except ValueError as error:
            return self.send({"error": str(error)}, 400)

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store):
        super().__init__(address, Handler)
        self.store, self.token = store, secrets.token_urlsafe(32)

def main():
    parser = argparse.ArgumentParser(description="GraphCore Studio — local visual agent builder")
    parser.add_argument("--port", type=int, default=None, help="Local port (default: 8787, then an available port)")
    parser.add_argument("--data", default=os.environ.get("GRAPHCORE_STUDIO_DATA", str(ROOT / "studio" / "data")))
    parser.add_argument("--plugin", action="append", default=[], help="Trusted local Python module file registering tools")
    args = parser.parse_args()
    load_dotenv(Path(args.data) / ".env")
    for i, filename in enumerate(args.plugin):
        spec = importlib.util.spec_from_file_location("studio_plugin_" + str(i), filename)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.register(register_tool)
    store = Store(args.data)
    try:
        server = Server(("127.0.0.1", args.port if args.port is not None else 8787), store)
    except OSError as error:
        if args.port is not None or getattr(error, "errno", None) != errno.EADDRINUSE:
            store.close()
            raise
        server = Server(("127.0.0.1", 0), store)
    print("GraphCore Studio: http://127.0.0.1:" + str(server.server_port), flush=True)
    print("Local files: " + str(store.root), flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); store.close()

if __name__ == "__main__": main()
