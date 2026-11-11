from datetime import date
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from planner.agent.adapters.fake import ScriptedModel
from planner.agent.models import AgentDecision, ProfileExtraction, ToolCall
from planner.graph.nodes.llm import agent as agent_module
from planner.graph.nodes.llm import intake as intake_module
from planner.graph.runtime import compiled, config
from planner.graph.state import PlanState, Profile


async def test_invented_reserves_pause_for_the_user(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = ScriptedModel(
        extractions=[
            ProfileExtraction(
                country="GB",
                gross_annual="85,000",
                company_profit="48,750",
                scottish_taxpayer=False,
            )
        ],
        decisions=[
            AgentDecision(
                action="call_tools",
                tool_calls=[
                    ToolCall(
                        name="dividend_capacity",
                        arguments={
                            "existing_paye_income": "85,000",
                            "company_profit": "48,750",
                            "director_salary": "0",
                            "distributable_reserves": "48,750",
                        },
                    )
                ],
            ),
            AgentDecision(
                action="ask",
                fields=["distributable_reserves"],
                message="What are your distributable reserves?",
            ),
        ],
    )
    monkeypatch.setattr(intake_module, "model", lambda: fake)
    monkeypatch.setattr(agent_module, "model", lambda: fake)
    monkeypatch.setenv("PLANNER_FAKE_MODEL", "1")
    monkeypatch.setenv("PLANNER_FAKE_SINK", "1")
    async with compiled(db_url) as graph:
        out = await graph.ainvoke(
            PlanState(
                messages=[
                    HumanMessage(
                        content=(
                            "I have 85,000 PAYE and 48,750 company profit. "
                            "How much dividend can I take?"
                        )
                    )
                ],
                profile=Profile(planning_date=date(2026, 10, 18)),
            ),
            config(str(uuid4())),
        )
    assert out["results"] == []
    assert out["missing"] == ["distributable_reserves"]
    assert out["__interrupt__"][0].value["fields"] == ["distributable_reserves"]


async def test_model_supplied_missing_income_pauses_for_the_user(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = ScriptedModel(
        extractions=[
            ProfileExtraction(country="GB", scottish_taxpayer=False),
        ],
        decisions=[
            AgentDecision(
                action="call_tools",
                tool_calls=[
                    ToolCall(
                        name="take_home",
                        arguments={"gross_annual": "42,000"},
                    )
                ],
            ),
            AgentDecision(
                action="ask",
                fields=["gross_annual"],
                message="What is your gross annual income?",
            ),
        ],
    )
    monkeypatch.setattr(intake_module, "model", lambda: fake)
    monkeypatch.setattr(agent_module, "model", lambda: fake)
    monkeypatch.setenv("PLANNER_FAKE_MODEL", "1")
    monkeypatch.setenv("PLANNER_FAKE_SINK", "1")
    async with compiled(db_url) as graph:
        out = await graph.ainvoke(
            PlanState(
                messages=[
                    HumanMessage(
                        content="I earn 3,500 a month in England. What is my take-home?"
                    )
                ],
                profile=Profile(planning_date=date(2026, 10, 18)),
            ),
            config(str(uuid4())),
        )
    assert out["results"] == []
    assert out["missing"] == ["gross_annual"]
    assert out["__interrupt__"][0].value["fields"] == ["gross_annual"]
