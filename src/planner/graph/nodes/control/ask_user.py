from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from planner.graph.state import PlanState


def ask_user(state: PlanState) -> dict[str, Any]:
    # This node re-runs from its first line on resume.
    # Nothing above interrupt() may have side effects.
    answer = interrupt(
        {"kind": "input", "fields": state.missing, "message": state.agent_message}
    )
    return {
        "messages": [HumanMessage(content=str(answer))],
        "awaiting_answer": True,
    }
