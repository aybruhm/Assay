from datetime import UTC, date, datetime
from typing import Any, TypedDict, cast

from langchain_core.messages import HumanMessage

from planner.agent.adapters.fake import ScriptedModel
from planner.agent.models import AgentDecision, ProfileExtraction, ToolCall
from planner.core.types import CalcLine, CalcResult
from planner.graph.nodes.control.prepare import prepare
from planner.graph.nodes.deterministic.validator import validate
from planner.graph.nodes.llm import agent as agent_module
from planner.graph.nodes.llm import intake as intake_module
from planner.graph.nodes.llm import narrate as narrate_module
from planner.graph.state import PlanState, Profile, Report, Validation
from planner.research.models import ResearchResult
from planner.rules.schema import RulePackRef

REF = RulePackRef(jurisdiction="GB", tax_year="2026-27", version=1)
NG_REF = RulePackRef(jurisdiction="NG", tax_year="2026", version=1)


def _state(**overrides: object) -> PlanState:
    kwargs: dict[str, object] = {"messages": [HumanMessage(content="hi")]}
    kwargs.update(overrides)
    return PlanState(**cast(dict[str, Any], kwargs))


class TestIntake:
    async def test_country_is_the_only_required_field(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[
                ProfileExtraction(
                    country="gb",
                    gross_annual="45,000",
                    scottish_taxpayer=False,
                )
            ]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        assert out["profile"].country == "GB"
        assert out["profile"].gross_annual == 450_000_000
        assert out["missing"] == []

    async def test_missing_country_is_listed(self, monkeypatch):
        fake = ScriptedModel(extractions=[ProfileExtraction()])
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        assert out["missing"] == ["country"]

    async def test_fact_fields_are_parsed(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[
                ProfileExtraction(
                    country="GB",
                    pension_income="10,000",
                    rental_income="12,000",
                    other_income="3,000",
                    student_loan_plan="Plan 2",
                    company_profit="100,000",
                    director_salary="12,570",
                    distributable_reserves="5,000",
                    pension_rate="6%",
                    savings_amount="10,000",
                    annual_growth_rate="0.05",
                    investment_years="10 years",
                )
            ]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        profile = out["profile"]
        assert profile.pension_income == 100_000_000
        assert profile.rental_income == 120_000_000
        assert profile.other_income == 30_000_000
        assert profile.student_loan_plan == "plan 2"
        assert profile.company_profit == 1_000_000_000
        assert profile.director_salary == 125_700_000
        assert profile.distributable_reserves == 50_000_000
        assert profile.pension_rate == 600
        assert profile.savings_amount == 100_000_000
        assert profile.annual_growth_rate == 500
        assert profile.investment_years == 10

    async def test_existing_profile_fields_are_not_overwritten(self, monkeypatch):
        fake = ScriptedModel(extractions=[ProfileExtraction(country="GB")])
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(
                profile=Profile(
                    planning_date=date(2026, 10, 1),
                    gross_annual=450_000_000,
                    scottish_taxpayer=False,
                )
            )
        )
        assert out["profile"].gross_annual == 450_000_000
        assert out["profile"].scottish_taxpayer is False

    async def test_shorthand_amounts_are_parsed(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[
                ProfileExtraction(
                    country="GB",
                    gross_annual="45k",
                    company_profit="100k",
                    distributable_reserves="33k",
                    savings_amount="20k",
                    annual_growth_rate="5%",
                    investment_years="10 years",
                    pension_rate="6%",
                )
            ]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        profile = out["profile"]
        assert profile.gross_annual == 450_000_000
        assert profile.company_profit == 1_000_000_000
        assert profile.distributable_reserves == 330_000_000
        assert profile.savings_amount == 200_000_000
        assert profile.annual_growth_rate == 500
        assert profile.investment_years == 10
        assert profile.pension_rate == 600

    async def test_monthly_amount_is_not_stored_as_annual(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[ProfileExtraction(country="GB", gross_annual="3,500 a month")]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        assert out["profile"].gross_annual is None

    async def test_naira_shorthand_is_parsed(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[
                ProfileExtraction(country="NG", gross_annual="12 million naira")
            ]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(profile=Profile(planning_date=date(2026, 10, 1)))
        )
        assert out["profile"].gross_annual == 120_000_000_000

    async def test_a_new_turn_clears_the_previous_tool_results(self, monkeypatch):
        fake = ScriptedModel(extractions=[ProfileExtraction(country="GB")])
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        out = await intake_module.intake(
            _state(
                profile=Profile(planning_date=date(2026, 10, 1)),
                results=[CalcResult("abc", "old", "1", {}, [CalcLine("x", 1)])],
                research=[
                    ResearchResult(
                        research_id="abc123abc123",
                        kind="search",
                        title="Old source",
                        url="https://www.gov.uk/old",
                        fetched_at=datetime(2026, 10, 19, tzinfo=UTC),
                    )
                ],
                tool_records=[],
            )
        )
        assert out["results"] == []
        assert out["research"] == []
        assert out["agent_steps"] == 0
        assert out["next_action"] is None

    async def test_an_answer_updates_the_profile_and_keeps_results(self, monkeypatch):
        fake = ScriptedModel(
            extractions=[
                ProfileExtraction(
                    country="GB",
                    gross_annual="45,000",
                    scottish_taxpayer=False,
                )
            ]
        )
        monkeypatch.setattr(intake_module, "model", lambda: fake)
        old_result = CalcResult("abc", "old", "1", {}, [CalcLine("x", 1)])
        out = await intake_module.intake(
            _state(
                profile=Profile(planning_date=date(2026, 10, 1)),
                awaiting_answer=True,
                results=[old_result],
                agent_steps=2,
            )
        )
        assert out["profile"].gross_annual == 450_000_000
        assert out["profile"].scottish_taxpayer is False
        assert out["results"] == [old_result]
        assert out["agent_steps"] == 2
        assert out["awaiting_answer"] is False


class TestPrepare:
    async def test_gb_routes_to_the_rule_pack(self):
        out = prepare(
            _state(profile=Profile(country="GB", planning_date=date(2026, 10, 1)))
        )
        assert out == {"jurisdiction": "GB", "rule_pack": REF}

    async def test_ng_routes_to_the_calendar_year_pack(self):
        out = prepare(
            _state(profile=Profile(country="NG", planning_date=date(2026, 7, 15)))
        )
        assert out == {"jurisdiction": "NG", "rule_pack": NG_REF}

    async def test_unsupported_country_fails_closed(self):
        out = prepare(
            _state(profile=Profile(country="FR", planning_date=date(2026, 10, 1)))
        )
        assert out == {"failure": "country not supported: FR"}

    async def test_missing_planning_date_fails_closed(self):
        out = prepare(_state(profile=Profile(country="GB")))
        assert out == {"failure": "planning date missing; the caller must set it"}

    async def test_no_pack_for_date_fails_closed(self):
        out = prepare(
            _state(profile=Profile(country="GB", planning_date=date(2027, 6, 1)))
        )
        assert out["failure"].startswith("no rule pack")


class TestAgent:
    async def test_ask_sets_the_question(self, monkeypatch):
        fake = ScriptedModel(
            decisions=[
                AgentDecision(
                    action="ask",
                    fields=["company_profit"],
                    message="What is the company profit?",
                )
            ]
        )
        monkeypatch.setattr(agent_module, "model", lambda: fake)
        out = await agent_module.agent(_state(profile=Profile(country="GB")))
        assert out["next_action"] == "ask"
        assert out["missing"] == ["company_profit"]
        assert out["agent_message"] == "What is the company profit?"
        assert out["agent_steps"] == 1

    async def test_call_tools_sets_the_pending_calls(self, monkeypatch):
        fake = ScriptedModel(
            decisions=[
                AgentDecision(
                    action="call_tools",
                    tool_calls=[
                        ToolCall(name="take_home", arguments={"gross_annual": "45,000"})
                    ],
                )
            ]
        )
        monkeypatch.setattr(agent_module, "model", lambda: fake)
        out = await agent_module.agent(_state(profile=Profile(country="GB")))
        assert out["next_action"] == "tools"
        assert out["pending_calls"] == [
            ToolCall(name="take_home", arguments={"gross_annual": "45,000"})
        ]

    async def test_respond_ends_the_tool_loop(self, monkeypatch):
        fake = ScriptedModel(decisions=[AgentDecision(action="respond")])
        monkeypatch.setattr(agent_module, "model", lambda: fake)
        out = await agent_module.agent(_state(profile=Profile(country="GB")))
        assert out["next_action"] == "respond"
        assert out["pending_calls"] == []

    async def test_step_limit_fails_closed(self, monkeypatch):
        fake = ScriptedModel()
        monkeypatch.setattr(agent_module, "model", lambda: fake)
        out = await agent_module.agent(
            _state(
                profile=Profile(country="GB"), agent_steps=agent_module.MAX_AGENT_STEPS
            )
        )
        assert out == {"failure": "agent step limit reached"}

    async def test_question_never_contains_an_em_dash(self, monkeypatch):
        fake = ScriptedModel(
            decisions=[
                AgentDecision(
                    action="ask",
                    fields=["director_salary"],
                    message="The salary the company pays you \u2014 if any",
                )
            ]
        )
        monkeypatch.setattr(agent_module, "model", lambda: fake)
        out = await agent_module.agent(_state(profile=Profile(country="GB")))
        assert out["agent_message"] == "The salary the company pays you, if any"

    async def test_payload_carries_the_tools_and_profile(self, monkeypatch):
        spy = SpyModel()
        monkeypatch.setattr(agent_module, "model", lambda: spy)
        await agent_module.agent(
            _state(
                profile=Profile(
                    country="GB",
                    planning_date=date(2026, 10, 1),
                    gross_annual=850_000_000,
                )
            )
        )
        assert spy.payload is not None
        assert "dividend_capacity" in spy.payload
        assert "85,000.00" in spy.payload


RESULT = CalcResult(
    result_id="9f2c1a3b4d5e",
    calculator="gb.take_home",
    calculator_version="1",
    inputs={"gross_annual": 450_000_000, "scottish_taxpayer": False},
    lines=[
        CalcLine(key="net_pay", amount=346_224_000),
        CalcLine(key="income_tax", amount=64_860_000),
    ],
)


class ValidateOut(TypedDict):
    validation: Validation
    report: Report


def _validate(text: str, validation: Validation | None = None) -> ValidateOut:
    state = _state(
        results=[RESULT],
        rule_pack=REF,
        report=Report(text=text),
        validation=validation or Validation(),
    )
    out = validate(state)
    return ValidateOut(
        validation=out["validation"],
        report=out["report"],
    )


class TestValidator:
    async def test_correct_report_passes(self):
        out = _validate(
            "Your net pay is £34,622.40 [r:9f2c1a3b4d5e.net_pay]. "
            "You pay £6,486.00 [r:9f2c1a3b4d5e.income_tax] in income tax."
        )
        assert out["validation"].status == "passed"
        assert out["validation"].attempts == 1
        assert out["validation"].mismatches == []
        cited = {
            (citation.result_id, citation.key, citation.shown)
            for citation in out["report"].citations
        }
        assert ("9f2c1a3b4d5e", "net_pay", "£34,622.40") in cited
        assert ("9f2c1a3b4d5e", "income_tax", "£6,486.00") in cited

    async def test_wrong_figure_is_rejected(self):
        out = _validate("Your net pay is £34,000.00 [r:9f2c1a3b4d5e.net_pay].")
        assert out["validation"].status == "failed"
        assert any(
            "£34,000.00 should be £34,622.40" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_unknown_result_id_is_rejected(self):
        out = _validate("You get £34,622.40 [r:deadbeef1234.net_pay].")
        assert any(
            "unknown result_id deadbeef1234" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_unknown_field_is_rejected(self):
        out = _validate("You get £34,622.40 [r:9f2c1a3b4d5e.nope].")
        assert any(
            "unknown field nope" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_uncited_figure_is_rejected(self):
        out = _validate("Your salary is 45,000 a year.")
        assert any(
            "uncited figure: '45,000'" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_recommendation_language_is_rejected(self):
        out = _validate(
            "You should take the full dividend. "
            "Your net pay is £34,622.40 [r:9f2c1a3b4d5e.net_pay]."
        )
        assert out["validation"].status == "failed"
        assert any(
            "recommendation language" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_neutral_comparison_of_options_passes(self):
        out = _validate(
            "Option A leaves £34,622.40 [r:9f2c1a3b4d5e.net_pay]. "
            "Option B leaves £6,486.00 [r:9f2c1a3b4d5e.income_tax]."
        )
        assert out["validation"].status == "passed"
        assert out["validation"].mismatches == []

    async def test_duplicate_citations_are_collapsed(self):
        out = _validate(
            "Your net pay is £34,622.40 [r:9f2c1a3b4d5e.net_pay]. "
            "Again, £34,622.40 [r:9f2c1a3b4d5e.net_pay]."
        )
        assert out["validation"].status == "passed"
        assert len(out["report"].citations) == 1

    async def test_rounding_edge_matches_display(self):
        out = _validate("Your net pay is £34,622.40 [r:9f2c1a3b4d5e.net_pay].")
        assert out["validation"].status == "passed"

    async def test_rate_figures_pass(self):
        result = CalcResult(
            result_id="9f2c1a3b4d5e",
            calculator="gb.lookup_rule",
            calculator_version="1",
            inputs={"rule_id": "gb.income_tax.basic_rate"},
            lines=[
                CalcLine(
                    key="value",
                    amount=2000,
                    display_as="rate",
                    source="https://www.gov.uk/income-tax-rates",
                )
            ],
        )
        state = _state(
            results=[result],
            rule_pack=REF,
            report=Report(text="The basic rate is 20.00% [r:9f2c1a3b4d5e.value]."),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "passed"
        assert out["report"].citations[0].shown == "20.00%"

    async def test_cited_rule_source_url_passes(self):
        result = CalcResult(
            result_id="9f2c1a3b4d5e",
            calculator="gb.lookup_rule",
            calculator_version="1",
            inputs={"rule_id": "gb.income_tax.basic_rate"},
            lines=[
                CalcLine(
                    key="value",
                    amount=2000,
                    display_as="rate",
                    source="https://www.gov.uk/income-tax-rates",
                )
            ],
        )
        state = _state(
            results=[result],
            rule_pack=REF,
            report=Report(
                text=(
                    "The basic rate is 20.00% [r:9f2c1a3b4d5e.value]. "
                    "Source: https://www.gov.uk/income-tax-rates."
                )
            ),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "passed"

    async def test_uncited_rule_source_url_is_rejected(self):
        result = CalcResult(
            result_id="9f2c1a3b4d5e",
            calculator="gb.lookup_rule",
            calculator_version="1",
            inputs={"rule_id": "gb.income_tax.basic_rate"},
            lines=[
                CalcLine(
                    key="value",
                    amount=2000,
                    display_as="rate",
                    source="https://www.gov.uk/income-tax-rates",
                )
            ],
        )
        state = _state(
            results=[result],
            rule_pack=REF,
            report=Report(text="See https://www.gov.uk/income-tax-rates."),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "failed"
        assert any(
            "uncited source: https://www.gov.uk/income-tax-rates" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_research_url_passes(self):
        research = ResearchResult(
            research_id="abc123abc123",
            kind="search",
            title="Income Tax rates",
            url="https://www.gov.uk/income-tax-rates",
            snippet="Rates and allowances.",
            fetched_at=datetime(2026, 10, 19, tzinfo=UTC),
        )
        state = _state(
            results=[],
            research=[research],
            rule_pack=REF,
            report=Report(
                text=("The official page is at https://www.gov.uk/income-tax-rates.")
            ),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "passed"

    async def test_unknown_url_is_rejected(self):
        state = _state(
            results=[],
            research=[],
            rule_pack=REF,
            report=Report(text="See https://example.com/tax."),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "failed"
        assert any(
            "uncited source: https://example.com/tax" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_naira_figures_pass(self):
        result = CalcResult(
            result_id="9f2c1a3b4d5e",
            calculator="ng.take_home",
            calculator_version="1",
            inputs={"gross_annual": 250_000_000_000, "annual_rent": 0},
            lines=[CalcLine(key="net_pay", amount=222_000_000_000)],
        )
        state = _state(
            results=[result],
            rule_pack=NG_REF,
            report=Report(
                text="Your net pay is ₦22,200,000.00 [r:9f2c1a3b4d5e.net_pay]."
            ),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "passed"
        assert out["report"].citations[0].shown == "₦22,200,000.00"

    async def test_wrong_naira_figure_is_rejected(self):
        result = CalcResult(
            result_id="9f2c1a3b4d5e",
            calculator="ng.take_home",
            calculator_version="1",
            inputs={"gross_annual": 250_000_000_000, "annual_rent": 0},
            lines=[CalcLine(key="net_pay", amount=222_000_000_000)],
        )
        state = _state(
            results=[result],
            rule_pack=NG_REF,
            report=Report(
                text="Your net pay is ₦22,000,000.00 [r:9f2c1a3b4d5e.net_pay]."
            ),
            validation=Validation(),
        )
        out = validate(state)
        assert out["validation"].status == "failed"
        assert any(
            "₦22,000,000.00 should be ₦22,200,000.00" in mismatch
            for mismatch in out["validation"].mismatches
        )

    async def test_attempts_counter_increments(self):
        out = _validate(
            "wrong [r:9f2c1a3b4d5e.nope].",
            validation=Validation(attempts=2, mismatches=["earlier"]),
        )
        assert out["validation"].attempts == 3

    async def test_validation_log_appends_to_existing_attempts(self):
        state = _state(
            results=[RESULT],
            rule_pack=REF,
            report=Report(text="Your net pay is £34,622.40 [r:9f2c1a3b4d5e.net_pay]."),
            validation=Validation(attempts=1),
            validation_log=[Validation(status="failed", attempts=1)],
        )
        out = validate(state)
        assert len(out["validation_log"]) == 2
        assert out["validation_log"][-1].status == "passed"


class SpyModel:
    def __init__(self) -> None:
        self.payload: str | None = None

    async def extract_profile(self, messages):
        raise NotImplementedError

    async def decide(self, system: str, payload: str) -> AgentDecision:
        self.payload = payload
        return AgentDecision(action="respond")

    async def narrate(self, system: str, payload: str) -> str:
        self.payload = payload
        return "narrated"


class TestNarrate:
    async def test_payload_carries_figures_and_markers(self, monkeypatch):
        spy = SpyModel()
        monkeypatch.setattr(narrate_module, "model", lambda: spy)
        state = _state(results=[RESULT], rule_pack=REF, validation=Validation())
        out = await narrate_module.narrate(state)
        assert out["report"].text == "narrated"
        assert spy.payload is not None
        assert "[r:9f2c1a3b4d5e.net_pay]" in spy.payload
        assert "£34,622.40" in spy.payload

    async def test_payload_carries_the_latest_question(self, monkeypatch):
        spy = SpyModel()
        monkeypatch.setattr(narrate_module, "model", lambda: spy)
        state = _state(
            messages=[HumanMessage(content="How can I minimize my taxes?")],
            results=[RESULT],
            rule_pack=REF,
            validation=Validation(),
        )
        await narrate_module.narrate(state)
        assert spy.payload is not None
        assert "How can I minimize my taxes?" in spy.payload

    async def test_payload_carries_the_conversation(self, monkeypatch):
        spy = SpyModel()
        monkeypatch.setattr(narrate_module, "model", lambda: spy)
        state = _state(
            messages=[
                HumanMessage(content="I earn 45,000 a year in England"),
                HumanMessage(content="How can I minimize my taxes?"),
            ],
            results=[RESULT],
            rule_pack=REF,
            validation=Validation(),
        )
        await narrate_module.narrate(state)
        assert spy.payload is not None
        assert "I earn 45,000 a year in England" in spy.payload
        assert "How can I minimize my taxes?" in spy.payload

    async def test_rejection_feedback_is_appended(self, monkeypatch):
        spy = SpyModel()
        monkeypatch.setattr(narrate_module, "model", lambda: spy)
        state = _state(
            results=[RESULT],
            rule_pack=REF,
            validation=Validation(mismatches=["£1.00 should be £2.00"]),
        )
        await narrate_module.narrate(state)
        assert spy.payload is not None
        assert "rejected for" in spy.payload
        assert "£1.00 should be £2.00" in spy.payload

    async def test_report_never_contains_an_em_dash(self, monkeypatch):
        class DashModel(SpyModel):
            async def narrate(self, system: str, payload: str) -> str:
                return "Net pay is \u00a334,622.40 [r:9f2c1a3b4d5e.net_pay] \u2014 after tax."

        monkeypatch.setattr(narrate_module, "model", lambda: DashModel())
        state = _state(results=[RESULT], rule_pack=REF, validation=Validation())
        out = await narrate_module.narrate(state)
        assert "\u2014" not in out["report"].text
        assert out["report"].text == (
            "Net pay is \u00a334,622.40 [r:9f2c1a3b4d5e.net_pay], after tax."
        )
