from typing import Any

from planner.agent import model
from planner.agent.models import ProfileExtraction
from planner.agent.parsing import parse_amount, parse_rate, parse_years
from planner.graph.state import PlanState, Profile, Validation


def _merge(current: Profile, new: ProfileExtraction) -> Profile:
    updates: dict[str, Any] = {}
    if new.country:
        updates["country"] = new.country.strip().upper()
    if new.scottish_taxpayer is not None:
        updates["scottish_taxpayer"] = new.scottish_taxpayer
    if new.student_loan_plan:
        updates["student_loan_plan"] = new.student_loan_plan.strip().lower()
    if new.gross_annual:
        try:
            updates["gross_annual"] = parse_amount(new.gross_annual)
        except ValueError:
            pass
    if new.pension_income:
        try:
            updates["pension_income"] = parse_amount(new.pension_income)
        except ValueError:
            pass
    if new.rental_income:
        try:
            updates["rental_income"] = parse_amount(new.rental_income)
        except ValueError:
            pass
    if new.other_income:
        try:
            updates["other_income"] = parse_amount(new.other_income)
        except ValueError:
            pass
    if new.company_profit:
        try:
            updates["company_profit"] = parse_amount(new.company_profit)
        except ValueError:
            pass
    if new.director_salary:
        try:
            updates["director_salary"] = parse_amount(new.director_salary)
        except ValueError:
            pass
    if new.distributable_reserves:
        try:
            updates["distributable_reserves"] = parse_amount(new.distributable_reserves)
        except ValueError:
            pass
    if new.savings_amount:
        try:
            updates["savings_amount"] = parse_amount(new.savings_amount)
        except ValueError:
            pass
    if new.annual_growth_rate:
        try:
            updates["annual_growth_rate"] = parse_rate(new.annual_growth_rate)
        except ValueError:
            pass
    if new.investment_years:
        try:
            updates["investment_years"] = parse_years(new.investment_years)
        except ValueError:
            pass
    if new.pension_rate:
        try:
            updates["pension_rate"] = parse_rate(new.pension_rate)
        except ValueError:
            pass
    return current.model_copy(update=updates)


async def intake(state: PlanState) -> dict[str, Any]:
    extracted = await model().extract_profile(state.messages)
    profile = _merge(state.profile, extracted)
    missing = [] if profile.country else ["country"]
    if state.awaiting_answer:
        return {
            "profile": profile,
            "missing": missing,
            "results": state.results,
            "research": state.research,
            "tool_records": state.tool_records,
            "pending_calls": [],
            "next_action": None,
            "agent_message": "",
            "agent_steps": state.agent_steps,
            "report": None,
            "validation": Validation(),
            "validation_log": [],
            "failure": None,
            "awaiting_answer": False,
        }
    return {
        "profile": profile,
        "missing": missing,
        "results": [],
        "research": [],
        "tool_records": [],
        "pending_calls": [],
        "next_action": None,
        "agent_message": "",
        "agent_steps": 0,
        "report": None,
        "validation": Validation(),
        "validation_log": [],
        "failure": None,
        "awaiting_answer": False,
    }
