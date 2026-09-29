# %% [markdown]
# LangGraph equivalent of examples/complex_deepseek_workflow.json
# Run these cells in order in Jupyter. The workflow routes to one specialist,
# validates a structured risk review, pauses for human feedback, then synthesizes.

# %% [markdown]
# Install dependencies (run once in a Jupyter cell):
# %pip install -U langgraph langchain-openrouter pydantic python-dotenv

# %%
import getpass
import json
import os
from typing import Literal, TypedDict

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

# Reads a local .env file if present. Or enter the key when prompted below.
load_dotenv()
if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = getpass.getpass("OpenRouter API key: ")

MODEL = "deepseek/deepseek-v4-pro-0813"


# %%
class ReviewRecord(BaseModel):
    summary: str
    risk_score: float = Field(ge=0, le=1)
    needs_human_review: bool
    top_risks: list[str]
    mitigations: list[str]
    next_step: str


class WorkflowState(TypedDict, total=False):
    request: str
    audience: str
    review_required: bool
    risk_threshold: float  # Present in the source JSON; its condition uses review_required.
    route: str
    analysis: str
    request_stats: dict
    review_record: dict
    validated_review: dict
    human_review: str
    final_report: str


def model(temperature: float, max_tokens: int, timeout: int = 120):
    return ChatOpenRouter(
        model=MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=2,
    )


# %% [markdown]
# The router and specialist nodes reproduce the JSON workflow's prompts.

# %%
def route_request(state: WorkflowState):
    response = model(temperature=0, max_tokens=32, timeout=90).invoke([
        ("system", "Classify the project request. Return exactly one word: architecture, security, or product. Choose architecture for design, implementation, performance, or roadmap questions; security for privacy, credential, or threat concerns; product for usability or adoption concerns."),
        ("user", state["request"]),
    ])
    route = response.content.strip().lower().split()[0].strip(".,:;`*_\"'")
    if route not in {"architecture", "security", "product"}:
        raise ValueError(f"Router returned unexpected category: {response.content!r}")
    return {"route": route}


def architecture_agent(state: WorkflowState):
    response = model(0.2, 1400).invoke([
        ("system", "You are a pragmatic C++ systems architect. Analyze the request for component boundaries, runtime behavior, failure modes, and an incremental delivery plan. Be specific and distinguish facts from assumptions."),
        ("user", f"Request: {state['request']}\nAudience: {state['audience']}"),
    ])
    return {"analysis": response.content}


def security_agent(state: WorkflowState):
    response = model(0.2, 1200).invoke([
        ("system", "You are an application security and reliability reviewer. Review the request for secrets handling, local data exposure, plugin/tool boundaries, retries, observability, and unsafe execution. Return a concise risk assessment with concrete mitigations."),
        ("user", f"Request: {state['request']}\nAudience: {state['audience']}\nIdentify the highest-priority risks and practical controls."),
    ])
    return {"analysis": response.content}


def product_agent(state: WorkflowState):
    response = model(0.3, 1200).invoke([
        ("system", "You are a product designer for local developer tools. Explain how a new user should build, inspect, configure, debug, and export an agent workflow. Recommend an approachable first-run experience and acceptance criteria."),
        ("user", f"Request: {state['request']}\nAudience: {state['audience']}"),
    ])
    return {"analysis": response.content}


def choose_specialist(state: WorkflowState) -> Literal[
    "architecture_agent", "security_agent", "product_agent"
]:
    return {
        "architecture": "architecture_agent",
        "security": "security_agent",
        "product": "product_agent",
    }[state["route"]]


# %% [markdown]
# The tool node is local Python, equivalent to the JSON `word_count` tool.

# %%
def measure_request(state: WorkflowState):
    text = state["request"]
    return {"request_stats": {"words": len(text.split()), "characters": len(text)}}


def structured_risk_review(state: WorkflowState):
    response = model(0, 1000).invoke([
        ("system", "Return one JSON object only with keys: summary (string), risk_score (number from 0 to 1), needs_human_review (boolean), top_risks (array of strings), mitigations (array of strings), next_step (string). Assess risk conservatively. Do not wrap the JSON in markdown fences."),
        ("user", f"Original request: {state['request']}\nSpecialist analysis: {state['analysis']}\nRequest size: {state['request_stats']}"),
    ])
    raw = response.content
    if isinstance(raw, list):
        raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
    # Pydantic both parses and validates model output before it enters graph state.
    record = ReviewRecord.model_validate_json(raw)
    return {"review_record": record.model_dump(), "validated_review": record.model_dump()}


def approval_checkpoint(state: WorkflowState):
    # LangGraph persists the state and surfaces this JSON-serializable payload.
    feedback = interrupt({
        "message": "Review the assessment. Enter approval notes or edits to continue.",
        "validated_review": state["validated_review"],
        "specialist_analysis": state["analysis"],
    })
    return {"human_review": str(feedback)}


def route_for_approval(state: WorkflowState) -> Literal["approval", "synthesize"]:
    # Matches the source JSON's conditional node (field=review_required, expected=true).
    return "approval" if state.get("review_required") is True else "synthesize"


def synthesize(state: WorkflowState):
    human_review = state.get("human_review", "No human review requested.")
    response = model(0.2, 1800).invoke([
        ("system", "Synthesize the specialist analysis and validated risk record into a useful project review. Include an executive summary, architecture, agent workflow, risks and controls, phased implementation, and testable acceptance criteria. Do not invent specialist findings. If human feedback exists, incorporate it explicitly."),
        ("user", f"Request: {state['request']}\nAudience: {state['audience']}\nSpecialist analysis: {state['analysis']}\nValidated risk review: {json.dumps(state['validated_review'], ensure_ascii=False)}\nHuman review response, if present: {human_review}\nRequest stats: {state['request_stats']}"),
    ])
    return {"final_report": response.content}


# %%
builder = StateGraph(WorkflowState)
builder.add_node("router", route_request)
builder.add_node("architecture_agent", architecture_agent)
builder.add_node("security_agent", security_agent)
builder.add_node("product_agent", product_agent)
builder.add_node("measure_request", measure_request)
builder.add_node("risk_review", structured_risk_review)
builder.add_node("approval", approval_checkpoint)
builder.add_node("synthesize", synthesize)

builder.add_edge(START, "router")
builder.add_conditional_edges("router", choose_specialist)
for specialist in ("architecture_agent", "security_agent", "product_agent"):
    builder.add_edge(specialist, "measure_request")
builder.add_edge("measure_request", "risk_review")
builder.add_conditional_edges(
    "risk_review",
    route_for_approval,
    {"approval": "approval", "synthesize": "synthesize"},
)
builder.add_edge("approval", "synthesize")
builder.add_edge("synthesize", END)

# InMemorySaver is convenient for this notebook session. For runs that must survive
# process restarts, replace it with LangGraph's SQLite or database checkpointer.
app = builder.compile(checkpointer=InMemorySaver())


# %% [markdown]
# Run the same sample request. The graph pauses at approval because review_required=True.

# %%
initial_state: WorkflowState = {
    "request": "Review this proposal for a local-first visual agent builder. It uses a C++ graph runtime, a browser UI, and OpenRouter for model access. Identify architecture risks and propose a phased implementation.",
    "audience": "A small engineering team",
    "review_required": True,
    "risk_threshold": 0.65,
}
config = {"configurable": {"thread_id": "deepseek-project-review-notebook"}}

result = app.invoke(initial_state, config=config)
pending = result.get("__interrupt__", ())
if pending:
    print(json.dumps(pending[0].value, indent=2, ensure_ascii=False))
else:
    print(result["final_report"])


# %% [markdown]
# After inspecting the paused review above, run this cell to resume. The text you enter
# is passed to the final synthesis as human review feedback.

# %%
if pending:
    human_feedback = input("Approval notes or edits (press Enter to approve as-is): ").strip()
    if not human_feedback:
        human_feedback = "Approved as-is."
    result = app.invoke(Command(resume=human_feedback), config=config)
    print(result["final_report"])
