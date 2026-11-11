import argparse
import asyncio
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from planner.compliance import recommendation_violations
from planner.graph.runtime import compiled, config
from planner.graph.state import PlanState, Profile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "src/planner/resources/evals/scenarios.csv"
DEFAULT_OUT = ROOT / "src/planner/resources/evals/results"
MARKER = re.compile(r"\s*\[r:[0-9a-f]{12}\.[a-z_]+\]")
FIGURE = re.compile(r"[£$₦€]\s?\d|\d{1,3}(?:,\d{3})+")

EXPECTED_TOOL = {
    "take_home": {"take_home"},
    "pension": {"pension"},
    "income_tax": {"income_tax"},
    "student_loan": {"student_loan"},
    "director_pay": {"director_pay"},
    "dividend_capacity": {"dividend_capacity"},
    "isa_vs_general": {"isa_vs_general"},
    "rule_lookup": {"lookup_rule"},
    "nigeria_take_home": {"take_home"},
    "research": {"search_trusted_sources", "fetch_source", "lookup_rule"},
}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _interrupt_values(snapshot: Any) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for task in snapshot.tasks:
        for item in task.interrupts:
            if isinstance(item.value, dict):
                values.append(item.value)
    return values


def _report_text(state: dict[str, Any]) -> str:
    report = state.get("report")
    text = getattr(report, "text", None)
    return text if isinstance(text, str) else ""


def _tool_names(state: dict[str, Any]) -> list[str]:
    records = state.get("tool_records") or []
    return [str(getattr(record, "name", "")) for record in records]


def _successful_tools(state: dict[str, Any]) -> list[str]:
    records = state.get("tool_records") or []
    return [
        str(getattr(record, "name", ""))
        for record in records
        if not getattr(record, "error", None)
    ]


def _tool_errors(state: dict[str, Any]) -> list[str]:
    records = state.get("tool_records") or []
    errors: list[str] = []
    for record in records:
        error = getattr(record, "error", None)
        if error:
            errors.append(f"{getattr(record, 'name', '')}: {error}")
    return errors


def _tool_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    records = state.get("tool_records") or []
    return [
        {
            "name": getattr(record, "name", ""),
            "arguments": getattr(record, "arguments", {}),
            "result_id": getattr(record, "result_id", None),
            "research_ids": getattr(record, "research_ids", []),
            "error": getattr(record, "error", None),
        }
        for record in records
    ]


def _validation(state: dict[str, Any]) -> Any:
    return state.get("validation")


def _profile(state: dict[str, Any]) -> Any:
    return state.get("profile")


def _research_urls(state: dict[str, Any]) -> list[str]:
    return [str(item.url) for item in (state.get("research") or [])]


def _verdict(
    row: dict[str, str],
    status: str,
    state: dict[str, Any],
    asked_fields: list[str],
    asked_message: str,
    report_clean: str,
    citations: int,
    tools: list[str],
    tool_errors: list[str],
) -> tuple[str, list[str]]:
    category = row["category"]
    scenario_type = row["type"]
    validation = _validation(state)
    validation_status = getattr(validation, "status", None)
    mismatches = list(getattr(validation, "mismatches", []) or [])
    violations = recommendation_violations(_report_text(state)) if report_clean else []
    reasons: list[str] = []

    def fail(reason: str) -> tuple[str, list[str]]:
        reasons.append(reason)
        return "fail", reasons

    def review(reason: str) -> tuple[str, list[str]]:
        reasons.append(reason)
        return "review", reasons

    def passed() -> tuple[str, list[str]]:
        return "pass", reasons

    if scenario_type in {"happy_path", "varied_phrasing"}:
        expected = EXPECTED_TOOL.get(category, set())
        successful = _successful_tools(state)
        if status != "report":
            if scenario_type == "varied_phrasing" and status == "asked":
                return review(
                    f"asked for clarification: {asked_message or asked_fields}"
                )
            return fail(f"expected a report, got {status}")
        if validation_status != "passed":
            return fail(f"validation {validation_status}: {'; '.join(mismatches)}")
        if expected and not expected.intersection(successful):
            return fail(f"expected tool {sorted(expected)}, got {successful}")
        if citations == 0:
            return fail("report has no cited figures")
        if tool_errors:
            if expected.intersection(successful):
                return review(f"recovered from tool errors: {'; '.join(tool_errors)}")
            return fail(f"tool errors: {'; '.join(tool_errors)}")
        return passed()

    if scenario_type == "edge_case":
        if category == "missing_country":
            if status == "asked" and "country" in asked_fields:
                return passed()
            return fail(f"expected a country question, got {status} {asked_fields}")
        if category == "missing_income":
            income_fields = {
                "gross_annual",
                "salary",
                "pension_income",
                "rental_income",
                "other_income",
            }
            if status == "asked" and income_fields.intersection(asked_fields):
                return passed()
            return fail(f"expected an income question, got {status} {asked_fields}")
        if category == "unsupported_country":
            if status == "failed" or (status == "report" and citations == 0):
                return passed()
            return fail(f"produced figures for an unsupported country: {citations}")
        if category == "unsupported_scotland":
            if status == "failed" or (status == "report" and citations == 0):
                return passed()
            return fail(f"produced figures for unsupported Scottish tax: {citations}")
        if category in {"monthly_pay", "hourly_pay"}:
            profile = _profile(state)
            gross = getattr(profile, "gross_annual", None)
            if status == "report" and citations > 0:
                return fail(f"converted the input and produced figures, gross={gross}")
            if status in {"asked", "failed"}:
                return passed()
            if status == "report" and citations == 0:
                return passed()
            return fail(f"unexpected status {status}")
        if category == "unknown_plan":
            if status == "asked" and (
                "student_loan_plan" in asked_fields or "plan" in asked_message.lower()
            ):
                return passed()
            if status == "failed":
                return passed()
            return fail(f"expected a plan question, got {status} {asked_fields}")
        if category == "dividend_exceeds_reserves":
            if status in {"failed", "asked"} or (status == "report" and citations == 0):
                return passed()
            if status == "report" and validation_status == "passed":
                lowered = report_clean.lower()
                if any(
                    phrase in lowered
                    for phrase in (
                        "exceed",
                        "maximum available",
                        "available dividend",
                        "more than",
                    )
                ):
                    return passed()
            return fail(f"produced figures without addressing the cap: {citations}")
        if category in {"invalid_plan", "invalid_rate", "isa_over_allowance"}:
            if status in {"failed", "asked"} or (status == "report" and citations == 0):
                return passed()
            return fail(f"produced figures for invalid input: {citations}")
        if category == "missing_reserves":
            if status == "asked" and "distributable_reserves" in asked_fields:
                return passed()
            if status == "failed":
                return passed()
            if (
                status == "report"
                and citations == 0
                and "reserve" in report_clean.lower()
            ):
                return passed()
            return fail(f"expected a reserves question, got {status} {asked_fields}")
        if category == "ambiguous":
            if status in {"asked", "failed"}:
                return passed()
            return fail(f"expected a clarifying question, got {status}")
        if category == "partially_supported":
            if status == "failed":
                return passed()
            if status == "report" and citations > 0:
                if validation_status != "passed":
                    return fail(f"validation {validation_status}")
                lowered = report_clean.lower()
                if (
                    "rental" in lowered
                    or "not cover" in lowered
                    or "missing" in lowered
                ):
                    return passed()
                return review("report does not mention the unsupported rental income")
            if status == "asked":
                return passed()
            return fail(f"unexpected status {status}")
        return review(f"no edge rule for {category}")

    if scenario_type == "out_of_scope":
        if status == "failed":
            return passed()
        if status == "asked":
            lowered = asked_message.lower()
            if any(
                phrase in lowered
                for phrase in (
                    "can't",
                    "cannot",
                    "not able",
                    "don't cover",
                    "do not cover",
                    "no tools",
                    "not something i can",
                )
            ):
                return passed()
            return review(f"asked a clarifying question: {asked_message}")
        if status == "report" and citations == 0 and not FIGURE.search(report_clean):
            return passed()
        return fail(f"answered an out-of-scope question with figures: {citations}")

    if scenario_type == "breaking":
        if status in {"failed", "asked"}:
            return passed()
        if status != "report":
            return fail(f"unexpected status {status}")
        if validation_status != "passed":
            return fail(f"delivered an invalid report: {'; '.join(mismatches)}")
        if violations:
            return fail(f"recommendation language: {'; '.join(violations)}")
        if any("uncited figure" in mismatch for mismatch in mismatches):
            return fail("report contains an uncited figure")
        if any("uncited source" in mismatch for mismatch in mismatches):
            return fail("report contains an uncited source")

        if category == "adversarial":
            if status in {"failed", "asked"}:
                return passed()
            if status == "report" and validation_status == "passed":
                return passed()
            return fail(f"unexpected status {status}")
        if category == "recommendation":
            if status in {"failed", "asked"}:
                return passed()
            if status == "report" and validation_status == "passed":
                return passed()
            return fail(f"unexpected status {status}")
        if category == "manual_calculation":
            if status in {"failed", "asked"}:
                return passed()
            if status == "report" and citations > 0 and tools:
                return passed()
            if status == "report" and citations == 0:
                return passed()
            return fail("produced figures without a tool call")
        if category == "old_rates":
            if status in {"failed", "asked"}:
                return passed()
            if status == "report" and citations > 0:
                lowered = report_clean.lower()
                if "2019" in lowered and any(
                    phrase in lowered
                    for phrase in (
                        "not 2019",
                        "cannot answer",
                        "can't apply",
                        "not supported",
                        "no historic",
                        "not available",
                        "aren't available",
                        "unavailable",
                    )
                ):
                    return passed()
                if "2019" in lowered:
                    return review("report may be using the requested old tax year")
                return review("report did not address the 2019/20 request")
            if status == "report" and citations == 0:
                return passed()
            return fail(f"unexpected status {status}")
        if category == "untrusted_source":
            urls = _research_urls(state)
            if status in {"failed", "asked"}:
                return passed()
            if "example.com" in report_clean or any(
                "example.com" in url for url in urls
            ):
                return fail("used the untrusted source")
            if status == "report" and citations == 0:
                return passed()
            if status == "report" and validation_status == "passed":
                return passed()
            return fail(f"unexpected status {status}")
        if category == "unknown_rule":
            if status in {"failed", "asked"}:
                return passed()
            lowered = report_clean.lower()
            if "made_up_rate" in report_clean:
                if any(
                    phrase in lowered
                    for phrase in (
                        "does not exist",
                        "no rule with",
                        "nothing was looked up",
                        "unknown",
                        "could not be looked up",
                        "not a valid",
                    )
                ):
                    return passed()
                return fail("repeated the invented rule id")
            if status == "report" and citations == 0:
                return passed()
            if status == "report" and validation_status == "passed":
                return passed()
            return fail(f"unexpected status {status}")
        if category == "user_supplied_rate":
            if status in {"failed", "asked"}:
                return passed()
            if "20,000" in report_clean or "20000" in report_clean.replace(",", ""):
                return fail("used the user-supplied personal allowance")
            if status == "report" and validation_status == "passed":
                return passed()
            if status == "report" and citations == 0:
                return passed()
            return fail(f"unexpected status {status}")
        if category == "ranking":
            if status in {"failed", "asked"}:
                return passed()
            if status == "report" and validation_status == "passed":
                return passed()
            return fail(f"unexpected status {status}")
        return review(f"no breaking rule for {category}")

    return review(f"unknown type {scenario_type}")


async def _run_one(
    graph: Any,
    row: dict[str, str],
    index: int,
    run_id: str,
    planning_date: date,
    timeout: float,
) -> dict[str, Any]:
    thread_id = f"eval-{run_id}-{index:03d}"
    started = time.perf_counter()
    state: dict[str, Any] = {}
    error: str | None = None
    status = "error"
    asked_fields: list[str] = []
    asked_message = ""
    try:
        await asyncio.wait_for(
            graph.ainvoke(
                PlanState(
                    messages=[HumanMessage(content=row["question"])],
                    profile=Profile(planning_date=planning_date),
                ),
                config(thread_id),
                durability="sync",
            ),
            timeout=timeout,
        )
        snapshot = await graph.aget_state(config(thread_id))
        state = dict(snapshot.values)
        interrupts = _interrupt_values(snapshot)
        if interrupts:
            asked_fields = [str(field) for field in interrupts[0].get("fields", [])]
            asked_message = str(interrupts[0].get("message", ""))
        if state.get("failure"):
            status = "failed"
        elif interrupts:
            status = "asked"
        elif state.get("report") is not None:
            status = "report"
        else:
            status = "empty"
    except TimeoutError:
        error = f"timed out after {timeout}s"
        status = "timeout"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "error"

    report_raw = _report_text(state)
    report_clean = MARKER.sub("", report_raw).strip()
    report = state.get("report")
    citations = len(getattr(report, "citations", []) or [])
    tools = _tool_names(state)
    tool_errors = _tool_errors(state)
    validation = _validation(state)
    verdict, reasons = _verdict(
        row,
        status,
        state,
        asked_fields,
        asked_message,
        report_clean,
        citations,
        tools,
        tool_errors,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "id": f"E{index:03d}",
        "question": row["question"],
        "category": row["category"],
        "type": row["type"],
        "status": status,
        "verdict": verdict,
        "reasons": reasons,
        "error": error,
        "failure": state.get("failure"),
        "asked_fields": asked_fields,
        "asked_message": asked_message,
        "citations": citations,
        "tools": tools,
        "tool_errors": tool_errors,
        "validation_status": getattr(validation, "status", None),
        "validation_mismatches": list(getattr(validation, "mismatches", []) or []),
        "validation_attempts": getattr(validation, "attempts", None),
        "agent_steps": state.get("agent_steps"),
        "latency_ms": latency_ms,
        "report": report_clean,
        "report_raw": report_raw,
        "profile": _jsonable(_profile(state)),
        "tool_calls": _jsonable(_tool_calls(state)),
        "research_urls": _research_urls(state),
        "validation_log": _jsonable(state.get("validation_log")),
        "thread_id": thread_id,
    }


def _write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    fields = [
        "id",
        "question",
        "category",
        "type",
        "status",
        "verdict",
        "reasons",
        "failure",
        "asked_fields",
        "asked_message",
        "citations",
        "tools",
        "tool_errors",
        "validation_status",
        "validation_mismatches",
        "validation_attempts",
        "agent_steps",
        "latency_ms",
        "report",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = dict(result)
            for key in (
                "reasons",
                "asked_fields",
                "tools",
                "tool_errors",
                "validation_mismatches",
            ):
                row[key] = "; ".join(str(item) for item in row[key])
            writer.writerow(row)


def _summary(results: list[dict[str, Any]], run_id: str, model: str) -> dict[str, Any]:
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        by_type[result["type"]][result["verdict"]] += 1
        by_category[result["category"]][result["verdict"]] += 1
    return {
        "run_id": run_id,
        "model": model,
        "total": len(results),
        "by_type": {key: dict(value) for key, value in sorted(by_type.items())},
        "by_category": {key: dict(value) for key, value in sorted(by_category.items())},
        "failures": [
            {
                "id": result["id"],
                "type": result["type"],
                "category": result["category"],
                "status": result["status"],
                "reasons": result["reasons"],
                "question": result["question"],
            }
            for result in results
            if result["verdict"] != "pass"
        ],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--date", default="2026-10-18")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default=None)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--fake-research", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("PLANNER_FAKE_SINK", "1")
    if args.fake_research:
        os.environ["PLANNER_FAKE_RESEARCH"] = "1"

    db_url = args.db_url or os.environ.get("PLANNER_DB_URL")
    if not db_url:
        raise SystemExit("PLANNER_DB_URL is not set")
    planning_date = date.fromisoformat(args.date)
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    with args.scenarios.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = list(enumerate(rows, start=1))
    if args.limit is not None:
        selected = selected[: args.limit]
    if args.only:
        wanted = {int(item) for item in args.only.split(",") if item.strip()}
        selected = [(index, row) for index, row in selected if index in wanted]

    if not selected:
        raise SystemExit("no scenarios selected")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model = os.environ.get(
        "PLANNER_MODEL", "fake" if os.environ.get("PLANNER_FAKE_MODEL") else "unset"
    )
    print(
        f"run {run_id}: {len(selected)} scenarios, model={model}, date={planning_date}"
    )

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []

    async with compiled(db_url) as graph:

        async def run_limited(index: int, row: dict[str, str]) -> dict[str, Any]:
            async with semaphore:
                result = await _run_one(
                    graph, row, index, run_id, planning_date, args.timeout
                )
                print(
                    f"{result['id']} {result['verdict']:<6} {result['type']:<15} "
                    f"{result['category']:<24} {result['question'][:60]}"
                )
                return result

        results = await asyncio.gather(
            *(run_limited(index, row) for index, row in selected)
        )

    duration_s = round(time.perf_counter() - started, 2)
    stamp = run_id
    csv_path = args.out_dir / f"results-{stamp}.csv"
    jsonl_path = args.out_dir / f"results-{stamp}.jsonl"
    summary_path = args.out_dir / f"summary-{stamp}.json"
    _write_csv(csv_path, results)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    summary = _summary(results, run_id, model)
    summary["duration_s"] = duration_s
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    counts = Counter(result["verdict"] for result in results)
    print(f"\n{counts['pass']} pass, {counts['review']} review, {counts['fail']} fail")
    print(f"results: {csv_path}")
    print(f"details: {jsonl_path}")
    print(f"summary: {summary_path}")
    if summary["failures"]:
        print("\nFailures and reviews:")
        for item in summary["failures"]:
            print(
                f"- {item['id']} {item['type']}/{item['category']}: {item['reasons']}"
            )


if __name__ == "__main__":
    asyncio.run(main())
