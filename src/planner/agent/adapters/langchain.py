from collections.abc import Sequence

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from planner.agent.models import AgentDecision, ProfileExtraction
from planner.agent.ports import ModelPort

INTAKE_PROMPT = """You are extracting a structured profile from a conversation with a user. Extract only facts the user has explicitly stated. Copy amounts exactly as written; do not round, convert, infer, or calculate anything. Leave a field empty if the corresponding fact was not stated.

Field mapping:
- Use gross_annual for an existing salary or PAYE income.
- Use pension_income, rental_income, and other_income for those income sources respectively.
- Use student_loan_plan for a plan name such as plan1, plan2, plan4, plan5, or postgraduate.
- Use company_profit for profit before director pay.
- Use director_salary for a salary paid by the company.
- Use distributable_reserves for retained profit available before this year's dividend.

Taxpayer status:
- If the user mentions England, Wales, or Northern Ireland, set scottish_taxpayer to false.
- If the user mentions Scotland, set scottish_taxpayer to true.

Rates and investments:
- If the user mentions a pension rate, extract it as written, for example 6% or 0.06. Do not convert it.
- If the user mentions savings, extract savings_amount, annual_growth_rate, and investment_years.

Amounts:
- Shorthand such as 45k, £45k, 45 grand, or 12 million naira is copied exactly as written. Do not expand or convert it.
- gross_annual is an annual figure. Do not map a monthly, weekly, daily, or hourly amount to gross_annual. Leave it empty and ask for the annual figure.

Always keep amounts exactly as the user wrote them."""


def _text_from_content(content: str | Sequence[object]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


class LangChainModel(ModelPort):
    def __init__(self, model: str) -> None:
        self._chat = init_chat_model(model)

    async def extract_profile(self, messages: list[AnyMessage]) -> ProfileExtraction:
        structured = self._chat.with_structured_output(ProfileExtraction)
        result = await structured.ainvoke([SystemMessage(INTAKE_PROMPT), *messages])
        assert isinstance(result, ProfileExtraction), (
            f"Expected ProfileExtraction, got {type(result).__name__}"
        )
        return result

    async def decide(self, system: str, payload: str) -> AgentDecision:
        structured = self._chat.with_structured_output(AgentDecision)
        result = await structured.ainvoke(
            [SystemMessage(system), HumanMessage(payload)]
        )
        assert isinstance(result, AgentDecision), (
            f"Expected AgentDecision, got {type(result).__name__}"
        )
        return result

    async def narrate(self, system: str, payload: str) -> str:
        response = await self._chat.ainvoke(
            [SystemMessage(system), HumanMessage(payload)]
        )
        return _text_from_content(response.content)
