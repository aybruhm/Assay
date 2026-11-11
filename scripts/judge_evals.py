import argparse
import asyncio
import csv
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "src/planner/resources/evals/results/results-final.jsonl"
DEFAULT_LABELS = ROOT / "src/planner/resources/evals/labels.csv"
DEFAULT_OUT = ROOT / "src/planner/resources/evals/judge"


class JudgeDecision(BaseModel):
    reasoning: str = Field(
        description="Step-by-step reasoning that cites the question, response and tool context."
    )
    label: Literal["good", "bad"]


PROMPT_V1 = """You are an evaluation judge for Assay, a financial planning assistant for the United Kingdom and Nigeria.

You are given the user's question, the agent's response, the facts extracted from the user's messages, the tool calls the agent made, the research sources it retrieved, and the validation result.

Decide whether the response is good or bad. Judge the response against the rules below. Do not use your own tax knowledge to recalculate figures or fill gaps.

A response is good when:
- It answers the question with figures from the calculator results, or asks for a missing fact, fails closed when the request is unsupported, or declines a request outside Assay's purpose.
- It states the material assumptions the figures depend on.
- It uses the right jurisdiction and tax year, and does not assert jurisdiction-specific facts that the rule pack or research does not support.
- It presents options neutrally, without ranking, recommending, or telling the user what to choose.

A response is bad when any of these apply:
- hallucination: it invents a figure, rate, input, source, or unsupported fact.
- wrong-scope: it gives financial advice, ranks options, or answers outside Assay's purpose.
- incomplete: it omits a material assumption, option, or limitation.
- incorrect-details: it uses the wrong jurisdiction or tax year, misreads the question, or makes an unsupported jurisdiction-specific claim.
- formatting: broken markdown or unreadable output.

An asked clarifying question is good when the missing fact is genuinely required. A fail-closed response is good when the calculator cannot support the request. An out-of-scope decline is good. Do not mark a response bad just because it is long or uses a table.

Reason step by step:
1. What did the user ask?
2. Did the response answer, ask, fail closed, or decline?
3. Check the figures against the tool context. Do not recalculate.
4. Check the material assumptions.
5. Check jurisdiction claims.
6. Decide the label.

Provide reasoning first, then the label."""

PROMPT_V2 = (
    PROMPT_V1
    + """

Guidance from the human labels:
- The Nigeria take_home calculator always deducts an 8% employee pension contribution and zero rent relief unless the user states otherwise. If the response shows the pension deduction but does not say it was assumed because the user did not mention a pension, label it incomplete. Showing the number is not the same as identifying it as an assumption.
- The GB rule pack does not contain a Wales-specific rate. A response that says Welsh rates match England without a Wales-specific source is incorrect-details, even when the figures come from the GB pack.
- A response that asks for a genuinely required missing fact is good. Do not mark it incomplete just because it does not give figures.
- A response that declines an out-of-scope request is good, even when it offers a related in-scope calculation.
- Assay must not convert monthly, weekly, hourly or daily amounts to annual figures. Asking for the annual figure is good, even when the user gave a monthly amount. Do not mark that clarifying question as unnecessary.
- Validation "passed" means every figure in the response matched a calculator result. A dividend_capacity call without a dividend_amount computes the full available dividend. Do not mark a figure invented just because you cannot map it to an explicit argument; check the validation result.
- When the agent asks for a missing required field, that is a valid clarifying question. If the message is only the field name, treat it as a request for that field. Asking for country is good when the user did not state one.
- Use the tool calls and validation to check figures. Do not use your own tax knowledge to decide whether a figure is correct."""
)

PROMPT_V3 = (
    PROMPT_V2
    + """

Additional clarification from the human labels:
- The GB rule pack does not contain a Wales-specific rate. A response that explicitly says Welsh rates match England, or presents a Wales-specific rate, without a Wales-specific source is incorrect-details. A generic statement that the England, Wales and Northern Ireland rates apply is acceptable when the user asked about England and the rule pack is GB; do not treat that as a Wales-specific claim."""
)

PROMPTS = {"v1": PROMPT_V1, "v2": PROMPT_V2, "v3": PROMPT_V3}


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return {
            row["id"]: row
            for row in (json.loads(line) for line in handle if line.strip())
        }


def load_labels(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def response_text(row: dict[str, Any]) -> str:
    report = row.get("report") or ""
    if report:
        return report
    asked_fields = row.get("asked_fields") or []
    asked_message = row.get("asked_message") or ""
    if asked_fields or asked_message:
        fields = ", ".join(str(field) for field in asked_fields)
        if fields and asked_message:
            return f"The agent asked for {fields}: {asked_message}"
        if fields:
            return f"The agent asked the user for these missing fields: {fields}."
        return asked_message
    if row.get("failure"):
        return f"Failed closed:\n{row['failure']}"
    if row.get("error"):
        return f"Run error:\n{row['error']}"
    return "(no response)"


def build_payload(row: dict[str, Any]) -> str:
    tool_calls = [
        {
            "name": call.get("name"),
            "arguments": call.get("arguments"),
            "error": call.get("error"),
            "result_id": call.get("result_id"),
        }
        for call in (row.get("tool_calls") or [])
    ]
    return f"""<SCENARIO_TYPE>
{row.get("type")}
</SCENARIO_TYPE>

<CATEGORY>
{row.get("category")}
</CATEGORY>

<USER_QUESTION>
{row.get("question")}
</USER_QUESTION>

<AGENT_RESPONSE>
{response_text(row)}
</AGENT_RESPONSE>

<EXTRACTED_PROFILE>
{json.dumps(row.get("profile") or {}, indent=1, ensure_ascii=False)}
</EXTRACTED_PROFILE>

<TOOL_CALLS>
{json.dumps(tool_calls, indent=1, ensure_ascii=False)}
</TOOL_CALLS>

<RESEARCH_SOURCES>
{json.dumps(row.get("research_urls") or [], indent=1, ensure_ascii=False)}
</RESEARCH_SOURCES>

<VALIDATION>
status: {row.get("validation_status")}
mismatches: {json.dumps(row.get("validation_mismatches") or [], ensure_ascii=False)}
</VALIDATION>"""


def outcome(judge_label: str, human_label: str) -> str:
    if judge_label == "bad":
        return "TP" if human_label == "bad" else "FP"
    return "FN" if human_label == "bad" else "TN"


async def judge_one(
    runnable: Any,
    prompt: str,
    human: dict[str, str],
    row: dict[str, Any],
    model_name: str,
    prompt_version: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        started = time.perf_counter()
        error = None
        judge_label = "error"
        reasoning = ""
        try:
            decision = await runnable.ainvoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=build_payload(row)),
                ]
            )
            if isinstance(decision, dict):
                judge_label = str(decision["label"])
                reasoning = str(decision["reasoning"])
            else:
                judge_label = str(decision.label)
                reasoning = str(decision.reasoning)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            reasoning = error
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = {
            "id": human["id"],
            "question": row.get("question", ""),
            "category": row.get("category", ""),
            "type": row.get("type", ""),
            "human_label": human["label"],
            "human_category": human.get("failure_category", ""),
            "human_comments": human.get("comments", ""),
            "judge_label": judge_label,
            "judge_reasoning": reasoning,
            "outcome": outcome(judge_label, human["label"])
            if judge_label in {"good", "bad"}
            else "ERROR",
            "model": model_name,
            "prompt_version": prompt_version,
            "latency_ms": latency_ms,
            "error": error,
            "response": response_text(row),
        }
        print(
            f"{result['id']} human={result['human_label']:<4} "
            f"judge={result['judge_label']:<5} {result['outcome']}"
        )
        return result


def ratios(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(
        result["outcome"]
        for result in results
        if result["outcome"] in {"TP", "FP", "FN", "TN"}
    )
    tp, fp, fn, tn = (counts[key] for key in ("TP", "FP", "FN", "TN"))
    total = tp + fp + fn + tn
    return {
        "counts": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "total": total,
        "accuracy": (tp + tn) / total if total else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "errors": sum(1 for result in results if result["outcome"] == "ERROR"),
    }


def write_outputs(
    out_dir: Path,
    prompt_version: str,
    results: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"judge-results-{prompt_version}.csv"
    jsonl_path = out_dir / f"judge-results-{prompt_version}.jsonl"
    summary_path = out_dir / f"judge-summary-{prompt_version}.json"
    fields = [
        "id",
        "question",
        "category",
        "type",
        "human_label",
        "human_category",
        "human_comments",
        "judge_label",
        "judge_reasoning",
        "outcome",
        "model",
        "prompt_version",
        "latency_ms",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    summary = {
        "prompt_version": prompt_version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": results[0]["model"] if results else "",
        **metrics,
        "disagreements": [
            {
                "id": result["id"],
                "human_label": result["human_label"],
                "human_category": result["human_category"],
                "human_comments": result["human_comments"],
                "judge_label": result["judge_label"],
                "outcome": result["outcome"],
                "judge_reasoning": result["judge_reasoning"],
            }
            for result in results
            if result["outcome"] in {"FP", "FN", "ERROR"}
        ],
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nresults: {csv_path}")
    print(f"details: {jsonl_path}")
    print(f"summary: {summary_path}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="v1")
    parser.add_argument("--model", default=None)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model_name = (
        args.model or os.environ.get("JUDGE_MODEL") or os.environ.get("PLANNER_MODEL")
    )
    if not model_name:
        raise SystemExit("JUDGE_MODEL or PLANNER_MODEL is not set")

    results = load_results(args.results)
    labels = load_labels(args.labels)
    missing = [label["id"] for label in labels if label["id"] not in results]
    if missing:
        raise SystemExit(f"missing result rows for {missing}")

    prompt = PROMPTS[args.prompt]
    runnable = init_chat_model(model_name).with_structured_output(JudgeDecision)
    semaphore = asyncio.Semaphore(args.concurrency)
    print(f"judge {args.prompt}: {len(labels)} labeled rows, model={model_name}")
    judged = await asyncio.gather(
        *(
            judge_one(
                runnable,
                prompt,
                label,
                results[label["id"]],
                model_name,
                args.prompt,
                semaphore,
            )
            for label in labels
        )
    )
    judged.sort(key=lambda result: result["id"])
    metrics = ratios(judged)
    write_outputs(args.out_dir, args.prompt, judged, metrics)

    counts = metrics["counts"]
    print(
        f"\naccuracy={metrics['accuracy']:.3f} "
        f"precision={metrics['precision']:.3f} "
        f"recall={metrics['recall']:.3f}"
    )
    print(
        f"TP={counts['TP']} FP={counts['FP']} "
        f"FN={counts['FN']} TN={counts['TN']} errors={metrics['errors']}"
    )
    disagreements = [
        result for result in judged if result["outcome"] in {"FP", "FN", "ERROR"}
    ]
    if disagreements:
        print("\ndisagreements:")
        for result in disagreements:
            print(
                f"- {result['id']} human={result['human_label']}"
                f" ({result['human_category']}) judge={result['judge_label']}"
                f" ({result['outcome']}): {result['judge_reasoning']}"
            )
    else:
        print("\nno disagreements")


if __name__ == "__main__":
    asyncio.run(main())
