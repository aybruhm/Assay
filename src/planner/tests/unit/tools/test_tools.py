from datetime import UTC, datetime

import pytest

from planner.agent.models import ToolCall
from planner.core.types import CalcResult
from planner.research.adapters.fake import FakeResearch
from planner.research.models import FetchedPage, SearchHit
from planner.research.ports import ResearchPort
from planner.rules.loader import load_pack
from planner.tools.execute import execute_tool
from planner.tools.specs import ToolContext, ToolError, tool_catalog


def _gb_context(
    defaults: dict[str, str | int | bool | None] | None = None,
    research: ResearchPort | None = None,
) -> ToolContext:
    return ToolContext(
        jurisdiction="GB",
        pack=load_pack("GB", "2026-27"),
        defaults=defaults or {},
        research=research,
    )


async def test_catalog_lists_the_supported_tools():
    names = {tool["name"] for tool in tool_catalog()}
    assert names == {
        "take_home",
        "pension",
        "director_pay",
        "dividend_capacity",
        "income_tax",
        "isa_vs_general",
        "student_loan",
        "lookup_rule",
        "search_trusted_sources",
        "fetch_source",
    }


async def test_catalog_declares_supported_jurisdictions():
    catalog = {tool["name"]: tool for tool in tool_catalog()}
    assert catalog["take_home"]["jurisdictions"] == ["GB", "NG"]
    assert catalog["lookup_rule"]["jurisdictions"] == ["GB", "NG"]
    assert catalog["pension"]["jurisdictions"] == ["GB"]
    assert catalog["dividend_capacity"]["jurisdictions"] == ["GB"]
    assert all(tool["jurisdictions"] for tool in catalog.values())


async def test_take_home_uses_explicit_arguments():
    result = await execute_tool(
        ToolCall(
            name="take_home",
            arguments={"gross_annual": "45,000", "scottish_taxpayer": False},
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.calculator == "gb.take_home"
    assert result.get("net_pay") == 359_196_000


async def test_take_home_falls_back_to_profile_defaults():
    result = await execute_tool(
        ToolCall(name="take_home", arguments={}),
        _gb_context(
            {
                "gross_annual": "45,000.00",
                "scottish_taxpayer": False,
            }
        ),
    )
    assert isinstance(result, CalcResult)
    assert result.get("net_pay") == 359_196_000


async def test_take_home_dispatches_to_nigeria():
    context = ToolContext(
        jurisdiction="NG",
        pack=load_pack("NG", "2026"),
        defaults={"gross_annual": "25,000,000"},
    )
    result = await execute_tool(ToolCall(name="take_home", arguments={}), context)
    assert isinstance(result, CalcResult)
    assert result.calculator == "ng.take_home"
    assert result.get("net_pay") == 187_400_000_000


async def test_dividend_capacity_uses_explicit_arguments():
    result = await execute_tool(
        ToolCall(
            name="dividend_capacity",
            arguments={
                "existing_paye_income": "85,000",
                "company_profit": "100,000",
                "distributable_reserves": "0",
                "scottish_taxpayer": False,
            },
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.calculator == "gb.dividend_capacity"
    assert result.get("available_dividend") == 772_500_000
    assert result.get("dividend_tax") == 292_266_050


async def test_director_salary_defaults_to_zero_for_dividend_capacity():
    result = await execute_tool(
        ToolCall(
            name="dividend_capacity",
            arguments={
                "existing_paye_income": "85,000",
                "company_profit": "100,000",
                "distributable_reserves": "0",
                "scottish_taxpayer": False,
            },
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.get("director_salary") == 0


async def test_missing_required_argument_raises_a_tool_error():
    with pytest.raises(ToolError) as excinfo:
        await execute_tool(ToolCall(name="take_home", arguments={}), _gb_context())
    assert "gross_annual is required" in excinfo.value.reason


async def test_unknown_tool_raises_a_tool_error():
    with pytest.raises(ToolError) as excinfo:
        await execute_tool(ToolCall(name="nope", arguments={}), _gb_context())
    assert "unknown tool" in excinfo.value.reason


async def test_invalid_rate_raises_a_tool_error():
    with pytest.raises(ToolError) as excinfo:
        await execute_tool(
            ToolCall(
                name="pension",
                arguments={
                    "gross_annual": "85,000",
                    "pension_rate": "not-a-rate",
                    "scottish_taxpayer": False,
                },
            ),
            _gb_context(),
        )
    assert "pension_rate is not a rate" in excinfo.value.reason


async def test_income_tax_combines_salary_and_pension_income():
    result = await execute_tool(
        ToolCall(
            name="income_tax",
            arguments={
                "salary": "45,000",
                "pension_income": "10,000",
                "scottish_taxpayer": False,
            },
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.calculator == "gb.income_tax"
    assert result.get("total_income") == 550_000_000
    assert result.get("income_tax") == 94_320_000
    assert result.get("national_insurance") == 25_944_000
    assert result.get("net_income") == 429_736_000


async def test_income_tax_applies_the_personal_allowance_taper():
    result = await execute_tool(
        ToolCall(
            name="income_tax",
            arguments={
                "salary": "120,000",
                "scottish_taxpayer": False,
            },
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.get("personal_allowance") == 25_700_000
    assert result.get("taxable_income") == 1_174_300_000


async def test_student_loan_plan_two():
    result = await execute_tool(
        ToolCall(
            name="student_loan",
            arguments={"gross_annual": "45,000", "plan": "plan2"},
        ),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    assert result.calculator == "gb.student_loan"
    assert result.get("threshold") == 293_850_000
    assert result.get("repayment_rate") == 900
    assert result.get("student_loan_repayment") == 14_053_500


async def test_lookup_rule_returns_a_rate_and_source():
    result = await execute_tool(
        ToolCall(name="lookup_rule", arguments={"rule_id": "gb.income_tax.basic_rate"}),
        _gb_context(),
    )
    assert isinstance(result, CalcResult)
    line = next(line for line in result.lines if line.key == "value")
    assert line.amount == 2000
    assert line.display_as == "rate"
    assert line.source == "https://www.gov.uk/income-tax-rates"


async def test_search_trusted_sources_returns_only_allowlisted_hits():
    fake = FakeResearch(
        hits=[
            SearchHit(
                title="Income Tax rates",
                url="https://www.gov.uk/income-tax-rates",
                snippet="Rates and allowances.",
            ),
            SearchHit(
                title="An unofficial page",
                url="https://example.com/tax",
                snippet="Ignore this.",
            ),
        ]
    )
    result = await execute_tool(
        ToolCall(
            name="search_trusted_sources",
            arguments={"query": "income tax rates", "max_results": 5},
        ),
        _gb_context(research=fake),
    )
    assert isinstance(result, list)
    assert [item.url for item in result] == ["https://www.gov.uk/income-tax-rates"]
    assert result[0].kind == "search"
    assert fake.queries == [("income tax rates", 5)]


async def test_fetch_source_returns_page_text():
    fetched_at = datetime(2026, 10, 19, tzinfo=UTC)
    fake = FakeResearch(
        pages={
            "https://www.gov.uk/income-tax-rates": FetchedPage(
                title="Income Tax rates",
                url="https://www.gov.uk/income-tax-rates",
                text="Income Tax rates and allowances.",
                fetched_at=fetched_at,
            )
        }
    )
    result = await execute_tool(
        ToolCall(
            name="fetch_source",
            arguments={"url": "https://www.gov.uk/income-tax-rates"},
        ),
        _gb_context(research=fake),
    )
    assert isinstance(result, list)
    assert result[0].kind == "page"
    assert result[0].text == "Income Tax rates and allowances."
    assert fake.fetches == ["https://www.gov.uk/income-tax-rates"]


async def test_fetch_source_rejects_a_non_trusted_url():
    with pytest.raises(ToolError) as excinfo:
        await execute_tool(
            ToolCall(
                name="fetch_source",
                arguments={"url": "https://example.com/tax"},
            ),
            _gb_context(research=FakeResearch()),
        )
    assert "not a trusted source" in excinfo.value.reason


async def test_gb_only_tool_fails_closed_for_nigeria():
    context = ToolContext(
        jurisdiction="NG",
        pack=load_pack("NG", "2026"),
        defaults={"gross_annual": "25,000,000"},
    )
    with pytest.raises(ToolError) as excinfo:
        await execute_tool(ToolCall(name="pension", arguments={}), context)
    assert "only supported for GB" in excinfo.value.reason
