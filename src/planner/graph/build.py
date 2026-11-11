import functools
import os
from collections.abc import Callable
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from planner.graph.nodes.control.ask_user import ask_user
from planner.graph.nodes.control.finish import deliver, fail_closed
from planner.graph.nodes.control.prepare import prepare
from planner.graph.nodes.deterministic.tools import execute_pending
from planner.graph.nodes.deterministic.validator import validate
from planner.graph.nodes.llm.agent import agent
from planner.graph.nodes.llm.intake import intake
from planner.graph.nodes.llm.narrate import narrate
from planner.graph.state import PlanState

MAX_NARRATION_ATTEMPTS = 3  # first draft plus two retries


def _crash_hook(name: str, node: Callable[..., object]) -> Callable[..., object]:
    if os.environ.get("PLANNER_CRASH_AT") != name:
        return node

    @functools.wraps(node)
    def crash(_state: PlanState, _config: RunnableConfig | None = None) -> object:
        os._exit(137)

    return crash


def _after_intake(state: PlanState) -> Literal["ask_user", "prepare"]:
    return "ask_user" if state.missing else "prepare"


def _after_prepare(state: PlanState) -> Literal["agent", "fail_closed"]:
    return "fail_closed" if state.failure else "agent"


def _after_agent(
    state: PlanState,
) -> Literal["execute_tools", "ask_user", "narrate", "fail_closed"]:
    if state.failure:
        return "fail_closed"
    if state.next_action == "tools":
        return "execute_tools"
    if state.next_action == "ask":
        return "ask_user"
    if state.next_action == "respond":
        return "narrate"
    return "fail_closed"


def _after_tools(state: PlanState) -> Literal["agent", "fail_closed"]:
    return "fail_closed" if state.failure else "agent"


def _after_narrate(state: PlanState) -> Literal["validate", "fail_closed"]:
    return "fail_closed" if state.failure else "validate"


def _after_validate(
    state: PlanState,
) -> Literal["deliver", "narrate", "fail_closed"]:
    if state.failure:
        return "fail_closed"
    if state.validation.status == "passed":
        return "deliver"
    if state.validation.attempts >= MAX_NARRATION_ATTEMPTS:
        return "fail_closed"
    return "narrate"


def _after_deliver(state: PlanState) -> Literal["fail_closed", "__end__"]:
    return "fail_closed" if state.failure else "__end__"


def build() -> StateGraph[PlanState, None, PlanState, PlanState]:
    graph = StateGraph[PlanState, None, PlanState, PlanState](PlanState)
    steps: dict[str, Callable[..., object]] = {
        "intake": intake,
        "ask_user": ask_user,
        "prepare": prepare,
        "agent": agent,
        "execute_tools": execute_pending,
        "narrate": narrate,
        "validate": validate,
        "deliver": deliver,
        "fail_closed": fail_closed,
    }
    for name, step in steps.items():
        graph.add_node(name, _crash_hook(name, step))

    graph.add_edge(START, "intake")
    graph.add_conditional_edges("intake", _after_intake)
    graph.add_edge("ask_user", "intake")
    graph.add_conditional_edges("prepare", _after_prepare)
    graph.add_conditional_edges("agent", _after_agent)
    graph.add_conditional_edges("execute_tools", _after_tools)
    graph.add_conditional_edges("narrate", _after_narrate)
    graph.add_conditional_edges("validate", _after_validate)
    graph.add_conditional_edges("deliver", _after_deliver)
    graph.add_edge("fail_closed", END)
    return graph
