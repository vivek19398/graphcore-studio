"""Uses only standard-library Python; replace retrieve with your library call."""
import asyncio
import sys
from graphcore import Graph, Interrupt, END

async def retrieve(state, context):
    await asyncio.sleep(0.01)
    return {"documents": ["C++ owns scheduling", "Python supplies integrations"]}

def approve(state, context):
    if not context.resumed:
        return Interrupt("Approve creating the summary? Reply yes or no.")
    return {"approved": context.response == "yes"}

def summarize(state, context):
    return {"summary": " | ".join(state["documents"]) if state["approved"] else "Declined"}

async def main():
    with Graph("python-agent-v1") as graph:
        graph.add_node("retrieve", retrieve).add_node("approve", approve).add_node("summarize", summarize)
        graph.set_entry("retrieve").add_edge("retrieve", "approve")
        graph.add_edge("approve", "summarize").add_edge("summarize", END)
        if len(sys.argv) > 1:
            result = await graph.aresume("python.checkpoint", response=sys.argv[1])
        else:
            result = await graph.ainvoke({"query": "architecture"}, checkpoint="python.checkpoint")
        print(result.prompt if result.suspended else result.state)

if __name__ == "__main__":
    asyncio.run(main())
