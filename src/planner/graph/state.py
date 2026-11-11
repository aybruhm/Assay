from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, StrictInt

from planner.agent.models import ToolCall
from planner.core.types import CalcResult
from planner.research.models import ResearchResult
from planner.rules.schema import RulePackRef


class Profile(BaseModel):
    country: str | None = None  # ISO 3166-1 alpha-2
    planning_date: date | None = None  # set by the caller at run start, never by a node
    gross_annual: StrictInt | None = None  # at fp.SCALE
    scottish_taxpayer: bool | None = None
    pension_income: StrictInt | None = None  # at fp.SCALE
    rental_income: StrictInt | None = None  # at fp.SCALE
    other_income: StrictInt | None = None  # at fp.SCALE
    student_loan_plan: str | None = None
    pension_rate: StrictInt | None = None  # at fp.SCALE
    company_profit: StrictInt | None = None  # at fp.SCALE
    director_salary: StrictInt | None = None  # at fp.SCALE
    distributable_reserves: StrictInt | None = None  # at fp.SCALE
    savings_amount: StrictInt | None = None  # at fp.SCALE
    annual_growth_rate: StrictInt | None = None  # at fp.SCALE
    investment_years: StrictInt | None = None


class ToolRecord(BaseModel):
    name: str
    arguments: dict[str, str | int | bool | None]
    result_id: str | None = None
    research_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class Citation(BaseModel):
    result_id: str
    key: str
    shown: str


class Report(BaseModel):
    text: str
    citations: list[Citation] = []


class Validation(BaseModel):
    status: Literal["pending", "passed", "failed"] = "pending"
    attempts: int = 0
    mismatches: list[str] = []


class Approval(BaseModel):
    """A human reviewer's decision, set by the compliance gate."""

    approved: bool
    reviewer: str
    note: str = ""


class PlanState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = []
    profile: Profile = Profile()
    missing: list[str] = []
    # Set while an answer is waiting to be merged back into the profile.
    awaiting_answer: bool = False
    jurisdiction: str | None = None
    rule_pack: RulePackRef | None = None
    results: list[CalcResult] = []
    research: list[ResearchResult] = []
    tool_records: list[ToolRecord] = []
    pending_calls: list[ToolCall] = []
    next_action: Literal["tools", "ask", "respond"] | None = None
    agent_message: str = ""
    agent_steps: int = 0
    report: Report | None = None
    validation: Validation = Validation()
    # Appended on every validator attempt so the audit trail keeps the history.
    validation_log: list[Validation] = []
    approval: Approval | None = None
    failure: str | None = None
