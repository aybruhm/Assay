import re
from typing import Any, Literal

from planner.compliance import recommendation_violations
from planner.display import SYMBOLS, display
from planner.graph.state import Citation, PlanState, Validation
from planner.rules.loader import NoRulePack, load_ref

# The currency symbol class derives from the one SYMBOLS table, so a new
# currency is matched without touching this node.
_SYMBOLS = "".join(re.escape(symbol) for symbol in SYMBOLS.values())

MARKED = re.compile(
    rf"(?P<shown>(?:[{_SYMBOLS}]-?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?%|true|false))"
    rf"\s*\[r:(?P<result_id>[0-9a-f]{{12}})\.(?P<key>[a-z_]+)\]"
)
# Anything that still looks like a figure after marked figures are removed.
UNMARKED = re.compile(
    rf"[{_SYMBOLS}]\s?\d|\d{{1,3}}(?:,\d{{3}})+|\d+\.\d+|\d+(?:\.\d+)?\s?%"
)
URL = re.compile(r"https?://[^\s)\]>,]+")


def validate(state: PlanState) -> dict[str, Any]:
    if state.report is None or state.rule_pack is None:
        return {"failure": "report or rule pack missing"}
    try:
        currency = load_ref(state.rule_pack).currency
    except NoRulePack as exc:
        return {"failure": str(exc)}
    by_id = {result.result_id: result for result in state.results}
    mismatches: list[str] = []
    citations: list[Citation] = []
    cited_sources: set[str] = set()

    for match in MARKED.finditer(state.report.text):
        result = by_id.get(match["result_id"])
        if result is None:
            mismatches.append(f"unknown result_id {match['result_id']}")
            continue
        line = next((line for line in result.lines if line.key == match["key"]), None)
        if line is None:
            mismatches.append(f"unknown field {match['key']} on {match['result_id']}")
            continue
        expected = display(line.amount, currency, line.display_as)
        if match["shown"] != expected:
            mismatches.append(
                f"{match['shown']} should be {expected} "
                f"for [r:{match['result_id']}.{match['key']}]"
            )
        else:
            citation = Citation(
                result_id=match["result_id"],
                key=match["key"],
                shown=expected,
            )
            if citation not in citations:
                citations.append(citation)
            if line.source:
                cited_sources.add(line.source)

    allowed_urls = {item.url for item in state.research} | cited_sources
    for match in URL.finditer(state.report.text):
        url = match.group().rstrip(".,;:")
        if url not in allowed_urls:
            mismatches.append(f"uncited source: {url}")

    without_urls = URL.sub("", state.report.text)
    for match in UNMARKED.finditer(MARKED.sub("", without_urls)):
        mismatches.append(f"uncited figure: {match.group()!r}")

    mismatches.extend(recommendation_violations(state.report.text))

    status: Literal["pending", "passed", "failed"] = (
        "failed" if mismatches else "passed"
    )
    validation = Validation(
        status=status,
        attempts=state.validation.attempts + 1,
        mismatches=mismatches,
    )
    return {
        "validation": validation,
        "validation_log": [*state.validation_log, validation],
        "report": state.report.model_copy(update={"citations": citations}),
    }
