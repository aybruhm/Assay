from planner.agent.models import ToolCall
from planner.graph.nodes.deterministic.tools import execute_pending
from planner.graph.state import PlanState, Profile
from planner.rules.schema import RulePackRef

REF = RulePackRef(jurisdiction="GB", tax_year="2026-27", version=1)


def _state(profile: Profile, calls: list[ToolCall]) -> PlanState:
    return PlanState(
        profile=profile,
        jurisdiction="GB",
        rule_pack=REF,
        pending_calls=calls,
    )


async def test_invented_reserves_are_not_used():
    state = _state(
        Profile(
            country="GB",
            gross_annual=850_000_000,
            company_profit=487_500_000,
            director_salary=0,
            scottish_taxpayer=False,
        ),
        [
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
    )
    out = await execute_pending(state)
    assert out["results"] == []
    assert out["tool_records"][0].error == "distributable_reserves is required"
    assert "distributable_reserves" not in out["tool_records"][0].arguments


async def test_profile_facts_override_model_arguments():
    state = _state(
        Profile(
            country="GB",
            gross_annual=450_000_000,
            scottish_taxpayer=False,
        ),
        [
            ToolCall(
                name="take_home",
                arguments={"gross_annual": "99,000", "scottish_taxpayer": True},
            )
        ],
    )
    out = await execute_pending(state)
    result = out["results"][0]
    assert result.inputs["gross_annual"] == 450_000_000
    assert result.inputs["scottish_taxpayer"] is False
    assert out["tool_records"][0].arguments == {}


async def test_missing_profile_income_cannot_be_supplied_by_model():
    state = _state(
        Profile(country="GB", scottish_taxpayer=False),
        [ToolCall(name="take_home", arguments={"gross_annual": "42,000"})],
    )
    out = await execute_pending(state)
    assert out["results"] == []
    assert out["tool_records"][0].error == "gross_annual is required"


async def test_optional_director_salary_falls_back_to_zero():
    state = _state(
        Profile(
            country="GB",
            gross_annual=850_000_000,
            company_profit=487_500_000,
            distributable_reserves=330_000_000,
            scottish_taxpayer=False,
        ),
        [
            ToolCall(
                name="dividend_capacity",
                arguments={"director_salary": "12,570"},
            )
        ],
    )
    out = await execute_pending(state)
    result = out["results"][0]
    assert result.inputs["director_salary"] == 0


async def test_dividend_amount_is_still_passed_through():
    state = _state(
        Profile(
            country="GB",
            gross_annual=850_000_000,
            company_profit=487_500_000,
            distributable_reserves=330_000_000,
            director_salary=0,
            scottish_taxpayer=False,
        ),
        [
            ToolCall(
                name="dividend_capacity",
                arguments={"dividend_amount": "15,000"},
            )
        ],
    )
    out = await execute_pending(state)
    result = out["results"][0]
    assert result.inputs["dividend_amount"] == 150_000_000
    assert out["tool_records"][0].arguments == {"dividend_amount": "15,000"}
