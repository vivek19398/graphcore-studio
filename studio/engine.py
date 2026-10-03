"""Validated visual workflow compiler. Scheduling and equality routing stay native."""
import copy
import hashlib
import importlib.util
import math
import json
import os
import re
from collections import Counter
from graphcore import Graph, Interrupt, Update, END

KINDS = {"input", "agent", "model", "condition", "tool", "retrieve", "data", "schema", "approval", "output"}
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
         "object": dict, "array": list}
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
TOOLS = {}
MODEL_PROVIDERS = {
    "openrouter": {"label": "OpenRouter", "package": "openrouter", "module": "openrouter", "env": ["OPENROUTER_API_KEY"], "models": []},
}
MESSAGE_ROLES = {"system", "user", "assistant"}

def register_tool(name, function, description="Custom Python integration"):
    if not KEY.fullmatch(name) or not callable(function):
        raise ValueError("Tools need a simple name and a callable")
    TOOLS[name] = {"function": function, "description": description}

register_tool("word_count", lambda value, config: {"words": len(str(value).split()),
    "characters": len(str(value))}, "Count words and characters")
register_tool("uppercase", lambda value, config: str(value).upper(), "Convert text to uppercase")
register_tool("parse_json", lambda value, config: json.loads(value) if isinstance(value, str) else value,
              "Parse text into a JSON object")
register_tool("keywords", lambda value, config: [word for word, _ in Counter(
    re.findall(r"[a-z]{4,}", str(value).lower())).most_common(6)], "Extract frequent keywords locally")

class WorkflowError(ValueError):
    pass

def pydantic_available():
    return importlib.util.find_spec("pydantic") is not None

def lookup(state, field):
    value = state
    for key in field.split("."):
        if not isinstance(value, dict) or key not in value:
            raise WorkflowError("State field is missing: " + field)
        value = value[key]
    return value

def render(template, state):
    def replace(match):
        value = lookup(state, match.group(1).strip())
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", replace, template)

def resolve_model(config, models=None):
    model = config.get("model", "")
    if isinstance(model, str) and model.startswith("$"):
        name = model[1:]
        if not KEY.fullmatch(name) or name not in (models or {}):
            raise WorkflowError("Unknown model variable: " + model + ". Add it in Model integrations.")
        return models[name]
    return model

def validate(workflow, models=None):
    errors = []
    if not isinstance(workflow, dict):
        return ["Workflow must be an object"]
    if workflow.get("format") != "graphcore.studio.v1":
        errors.append("Unsupported format; expected graphcore.studio.v1")
    nodes, edges = workflow.get("nodes"), workflow.get("edges")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        return errors + ["A workflow needs between 1 and 100 nodes"]
    if not isinstance(edges, list) or len(edges) > 300:
        return errors + ["Edges must be a list with at most 300 entries"]
    ids = set()
    inputs, outputs = [], []
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("Each node must be an object")
            continue
        ident, kind = node.get("id"), node.get("type")
        if not isinstance(ident, str) or not KEY.fullmatch(ident) or ident in ids:
            errors.append("Node IDs must be unique identifiers")
            continue
        ids.add(ident)
        if not isinstance(kind, str) or kind not in KINDS:
            errors.append(ident + ": unknown node type")
        if kind == "input": inputs.append(ident)
        if kind == "output": outputs.append(ident)
        config = node.get("config", {})
        if not isinstance(config, dict):
            errors.append(ident + ": config must be an object")
            continue
        for field in ("output_key",):
            if field in config and (not isinstance(config[field], str) or not KEY.fullmatch(config[field])):
                errors.append(ident + ": output key must be a simple identifier")
        if kind == "condition":
            if not isinstance(config.get("field"), str) or not KEY.fullmatch(config["field"]):
                errors.append(ident + ": condition requires a top-level state field")
            if "expected" not in config:
                errors.append(ident + ": expected value is required")
        if kind in ("agent", "model"):
            provider = config.get("provider", "demo")
            if not isinstance(provider, str) or (provider != "demo" and provider not in MODEL_PROVIDERS):
                errors.append(ident + ": choose a supported chat-model provider")
            if provider != "demo" and isinstance(provider, str) and provider in MODEL_PROVIDERS:
                module = MODEL_PROVIDERS[provider]["module"]
                try: installed = importlib.util.find_spec(module) is not None
                except (ImportError, ValueError): installed = False
                if not installed: errors.append(ident + ": install " + MODEL_PROVIDERS[provider]["package"] + " in the Studio Python environment")
            for field in ("prompt", "system", "demo_response", "model", "endpoint"):
                if field in config and not isinstance(config[field], str): errors.append(ident + ": " + field + " must be text")
            if provider != "demo" and (not isinstance(config.get("model"), str) or not config["model"].strip() or len(config["model"]) > 200):
                errors.append(ident + ": choose a model identifier (1–200 characters)")
            elif provider != "demo":
                try: resolve_model(config, models)
                except WorkflowError as error: errors.append(ident + ": " + str(error))
            if "temperature" in config and (isinstance(config["temperature"], bool) or not isinstance(config["temperature"], (int,float)) or not math.isfinite(config["temperature"]) or not 0 <= config["temperature"] <= 2):
                errors.append(ident + ": temperature must be between 0 and 2")
            if "max_tokens" in config and (isinstance(config["max_tokens"], bool) or not isinstance(config["max_tokens"], int) or not 1 <= config["max_tokens"] <= 200000):
                errors.append(ident + ": max tokens must be between 1 and 200000")
            if "timeout" in config and (isinstance(config["timeout"], bool) or not isinstance(config["timeout"], (int,float)) or not math.isfinite(config["timeout"]) or not 1 <= config["timeout"] <= 600):
                errors.append(ident + ": timeout must be between 1 and 600 seconds")
            if "max_retries" in config and (isinstance(config["max_retries"], bool) or not isinstance(config["max_retries"], int) or not 0 <= config["max_retries"] <= 10):
                errors.append(ident + ": max retries must be between 0 and 10")
            if "reasoning_effort" in config and config["reasoning_effort"] not in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
                errors.append(ident + ": reasoning effort must be none, minimal, low, medium, high, xhigh, or max")
            messages = config.get("messages")
            if messages is not None:
                if not isinstance(messages, list) or not 1 <= len(messages) <= 20: errors.append(ident + ": provide 1–20 chat messages")
                else:
                    for message in messages:
                        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or message.get("role") not in MESSAGE_ROLES or not isinstance(message.get("content"), str):
                            errors.append(ident + ": each message needs a system, user, or assistant role and text content")
                            break
        if kind == "tool" and config.get("tool", "word_count") not in TOOLS:
            errors.append(ident + ": unknown registered tool")
        if kind == "data":
            if not isinstance(config.get("column"), str) or not config["column"].strip():
                errors.append(ident + ": choose a numeric column")
            if not isinstance(config.get("input_field"), str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,255}", config["input_field"]):
                errors.append(ident + ": choose a table reference state field")
        if kind == "retrieve":
            if not isinstance(config.get("input_field", "input"), str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,255}", config.get("input_field", "input")):
                errors.append(ident + ": retrieval requires a state field, such as input or request.question")
            if "top_k" in config and (isinstance(config["top_k"], bool) or not isinstance(config["top_k"], int) or not 1 <= config["top_k"] <= 10):
                errors.append(ident + ": results must be between 1 and 10")
        if kind == "schema":
            fields = config.get("fields", [])
            if not isinstance(fields, list) or not fields or len(fields) > 50:
                errors.append(ident + ": define 1–50 schema fields")
            else:
                names = set()
                for field in fields:
                    if not isinstance(field, dict):
                        errors.append(ident + ": invalid schema field"); continue
                    name = field.get("name")
                    if not isinstance(name, str) or not KEY.fullmatch(name) or name in names:
                        errors.append(ident + ": invalid or duplicate schema field")
                    else: names.add(name)
                    if field.get("type") not in TYPES:
                        errors.append(ident + ": unsupported schema type")
            if config.get("engine", "builtin") not in ("builtin", "pydantic"):
                errors.append(ident + ": invalid schema engine")
            if config.get("engine") == "pydantic" and not pydantic_available():
                errors.append(ident + ": install pydantic in the server Python environment to use this engine")
    if errors: return errors
    if len(inputs) != 1: errors.append("Use exactly one Input node")
    if not outputs: errors.append("Add at least one Output node")
    outgoing = {key: [] for key in ids}
    incoming = {key: [] for key in ids}
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("Each edge must be an object"); continue
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in ids or target not in ids:
            errors.append("Every connection must link existing nodes"); continue
        outgoing[source].append(edge)
        incoming[target].append(edge)
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") not in outgoing: continue
        ident, kind = node["id"], node.get("type")
        routes = outgoing[ident]
        if kind == "output" and routes: errors.append(ident + ": Output cannot have outgoing connections")
        elif kind == "condition":
            if len(routes) != 2 or {e.get("port") for e in routes} != {"true", "false"}:
                errors.append(ident + ": connect both true and false branches exactly once")
        elif kind != "output" and (len(routes) != 1 or routes[0].get("port", "next") != "next"):
            errors.append(ident + ": connect exactly one next output")
        if kind == "input" and incoming[ident]: errors.append("Input cannot have incoming connections")
    if len(inputs) == 1:
        seen, pending = set(), [inputs[0]]
        while pending:
            ident = pending.pop()
            if ident in seen: continue
            seen.add(ident)
            pending.extend(e["target"] for e in outgoing[ident])
        for ident in sorted(ids - seen): errors.append(ident + ": node is not reachable from Input")
        # Every reachable node must have some path to an output; guarded cycles remain allowed.
        can_end, pending = set(), outputs[:]
        while pending:
            ident = pending.pop()
            if ident in can_end: continue
            can_end.add(ident)
            pending.extend(e["source"] for e in incoming[ident])
        for ident in sorted(seen - can_end): errors.append(ident + ": no path to an Output")
    return errors

def structured(value, fields, engine="builtin"):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise WorkflowError("Structured output must be a JSON object")
    allowed = {field["name"] for field in fields}
    extra = set(value) - allowed
    if extra: raise WorkflowError("Unexpected fields: " + ", ".join(sorted(extra)))
    # Common strict contract for the portable validator and Pydantic.
    for field in fields:
        name, kind = field["name"], field["type"]
        if name not in value:
            if field.get("required", True): raise WorkflowError("Required field missing: " + name)
            continue
        item = value[name]
        valid = isinstance(item, TYPES[kind])
        if kind in ("integer", "number") and isinstance(item, bool): valid = False
        if not valid: raise WorkflowError(name + " must be " + kind)
    if engine == "pydantic":
        from pydantic import create_model, StrictStr, StrictInt, StrictFloat, StrictBool
        from typing import Optional, Union
        types = {"string": StrictStr, "integer": StrictInt, "number": Union[StrictInt, StrictFloat],
                 "boolean": StrictBool, "object": dict, "array": list}
        definitions = {f["name"]: (types[f["type"]], ...) if f.get("required", True)
                       else (Optional[types[f["type"]]], None) for f in fields}
        model = create_model("StudioOutput", **definitions)
        parsed = model(**value)
        return parsed.model_dump(exclude_unset=True) if hasattr(parsed, "model_dump") else parsed.dict(exclude_unset=True)
    return value

def provider_availability():
    status = []
    for key, meta in MODEL_PROVIDERS.items():
        try: installed = importlib.util.find_spec(meta["module"]) is not None
        except (ImportError, ValueError): installed = False
        status.append({"id": key, "label": meta["label"], "package": meta["package"], "env": meta["env"],
                       "installed": installed, "models": meta["models"]})
    return status

def chat_messages(config, state):
    messages = config.get("messages")
    if not messages:
        messages = [{"role":"system", "content":config.get("system", "You are a helpful assistant.")},
                    {"role":"user", "content":config.get("prompt", "{{input}}") }]
    return [{"role":message["role"], "content":render(message["content"], state)} for message in messages]

def invoke_model(config, state, models=None):
    provider = config.get("provider", "demo")
    if provider == "demo":
        text = render(config.get("demo_response", "Demo response for {{input}}"), state)
        return json.loads(text) if config.get("json_output") else text
    meta = MODEL_PROVIDERS.get(provider)
    if not meta: raise WorkflowError("This initial release supports OpenRouter models. Choose OpenRouter or the offline fixture.")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key: raise WorkflowError("Configure OPENROUTER_API_KEY in Model integrations before running this model.")
    model_id = resolve_model(config, models)
    if not isinstance(model_id, str) or not model_id.strip():
        raise WorkflowError("Enter an OpenRouter model ID, such as openai/gpt-4o-mini.")
    try:
        from openrouter import OpenRouter
    except ImportError as error:
        raise WorkflowError("Install the OpenRouter SDK in the Studio Python environment: python -m pip install openrouter") from error
    kwargs = {"model":model_id, "messages":chat_messages(config, state), "stream":False,
              "temperature":config.get("temperature", 0.2),
              "max_completion_tokens":config.get("max_tokens", 1024),
              "timeout_ms":round(config.get("timeout", 60) * 1000)}
    if config.get("reasoning_effort"):
        kwargs["reasoning_effort"] = config["reasoning_effort"]
    if config.get("json_output"): kwargs["response_format"] = {"type":"json_object"}
    try:
        with OpenRouter(api_key=api_key) as client:
            result = client.chat.send(**kwargs)
    except Exception as error:
        detail = str(error).replace(api_key, "[redacted]")[:700]
        raise WorkflowError(type(error).__name__ + ": " + detail) from error
    def field(value, name, default=None):
        return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)

    choices = field(result, "choices", []) or []
    if not choices: raise WorkflowError("OpenRouter returned no completion choices")
    choice = choices[0]
    message = field(choice, "message", {}) or {}
    content = field(message, "content")
    if isinstance(content, list):
        content = "".join(str(text) for part in content if (text := field(part, "text")))
    if content is None or not str(content).strip():
        # Reasoning models may spend the full output budget on hidden reasoning and
        # return no user-facing content. Retry once with a larger budget, then give
        # an actionable diagnostic instead of silently passing an empty answer.
        if not config.get("_content_retry"):
            retry = dict(config)
            retry["_content_retry"] = True
            retry["max_tokens"] = min(max(config.get("max_tokens", 1024) * 2, 128), 8192)
            # A reasoning-only response often means hidden reasoning consumed the
            # entire completion limit. Ask for a direct answer on the single retry.
            retry["reasoning_effort"] = "none"
            return invoke_model(retry, state, models)
        finish_reason = field(choice, "finish_reason", "unknown")
        reasoning = field(message, "reasoning")
        reason = " The model returned reasoning but no visible answer." if reasoning else ""
        raise WorkflowError(f"OpenRouter returned no visible answer (finish reason: {finish_reason}). Increase max tokens or try a model route that returns standard chat content.{reason}")
    if config.get("json_output"):
        if isinstance(content, str): return json.loads(content)
        return content
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

def compile_workflow(workflow, emit=lambda kind, **data: None, models=None, retrieve=None, summarize=None):
    errors = validate(workflow, models)
    if errors: raise WorkflowError("\n".join(errors))
    version = hashlib.sha256(json.dumps(workflow, sort_keys=True).encode()).hexdigest()
    graph = Graph(version)
    outgoing = {}
    for edge in workflow["edges"]: outgoing.setdefault(edge["source"], {})[edge.get("port", "next")] = edge["target"]
    def callback(node):
        config, kind, ident = node.get("config", {}), node["type"], node["id"]
        def execute(state, context):
            key = config.get("output_key", ident)
            if kind == "input":
                result = {}
            elif kind in ("agent", "model"):
                model_id = resolve_model(config, models) if config.get("provider", "demo") != "demo" else ""
                emit("model.started", node=ident, provider=config.get("provider", "demo"), model=model_id)
                result = {key: invoke_model(config, state, models)}
                emit("model.completed", node=ident, provider=config.get("provider", "demo"), model=model_id)
            elif kind == "tool":
                value = lookup(state, config.get("input_field", "input"))
                result = {key: TOOLS[config.get("tool", "word_count")]["function"](copy.deepcopy(value), copy.deepcopy(config))}
            elif kind == "data":
                if summarize is None: raise WorkflowError("Local tables are unavailable")
                result = {key: summarize(lookup(state, config["input_field"]), config["column"])}
            elif kind == "retrieve":
                if retrieve is None: raise WorkflowError("Local document retrieval is unavailable")
                query = lookup(state, config.get("input_field", "input"))
                if not isinstance(query, str): query = json.dumps(query, ensure_ascii=False)
                result = {key: retrieve(config.get("library", "default"), query, config.get("top_k", 4))}
            elif kind == "schema":
                result = {key: structured(lookup(state, config.get("input_field", "input")), config["fields"], config.get("engine", "builtin"))}
            elif kind == "approval":
                if not context.resumed:
                    return Interrupt(render(config.get("prompt", "Approve this result?"), state))
                result = {key: context.response}
            elif kind == "output":
                result = {"output": render(config.get("template", "{{input}}"), state)}
            else: raise WorkflowError("Unknown executable node")
            json.dumps(result, allow_nan=False)
            emit("node.output", node=ident, updates=result)
            return result
        return execute
    try:
        for node in workflow["nodes"]:
            ident, kind, config = node["id"], node["type"], node.get("config", {})
            if kind == "condition":
                graph.add_condition(ident, config["field"], config["expected"], outgoing[ident]["true"], outgoing[ident]["false"])
            else:
                graph.add_node(ident, callback(node))
                graph.add_edge(ident, END if kind == "output" else outgoing[ident]["next"])
            if kind == "input": graph.set_entry(ident)
        graph.observe(lambda kind, node: emit(kind, node=node))
        return graph
    except BaseException:
        graph.close()
        raise
