import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
RESULTS_FILE = ROOT / "src/planner/resources/evals/results/results-final.jsonl"
LABELS_FILE = ROOT / "src/planner/resources/evals/labels.csv"
LABEL_VALUES = ["good", "bad"]
FAILURE_CATEGORIES = [
    "hallucination",
    "wrong-scope",
    "incomplete",
    "incorrect-details",
    "formatting",
    "other",
]
RUBRIC = """
**Good**
- Answers the question with figures grounded in tool results.
- Asks for a missing fact when a calculator needs it.
- Fails closed when a country, year, or input is unsupported.
- Declines requests outside Assay's purpose.
- States the material assumptions the figures depend on.
- Presents options neutrally, without ranking or selecting one.

**Bad**
- `hallucination`: invents a figure, rate, input, source, or unsupported fact.
- `wrong-scope`: gives financial advice, ranks options, or answers outside Assay's purpose.
- `incomplete`: omits a material assumption, option, or limitation.
- `incorrect-details`: wrong jurisdiction, tax year, or misread fact.
- `formatting`: broken markdown or unreadable output.
- `other`: anything else that makes the response unusable.
"""


def load_results() -> list[dict[str, Any]]:
    if not RESULTS_FILE.exists():
        return []
    with RESULTS_FILE.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return sorted(rows, key=lambda row: row["id"])


def load_labels() -> dict[str, dict[str, str]]:
    if not LABELS_FILE.exists():
        return {}
    with LABELS_FILE.open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def save_labels(labels: dict[str, dict[str, str]]) -> None:
    LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "label", "failure_category", "comments", "labeled_at"]
    with LABELS_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in sorted(labels):
            writer.writerow(labels[key])


def first_unlabeled(
    runs: list[dict[str, Any]], labels: dict[str, dict[str, str]]
) -> int:
    for index, run in enumerate(runs):
        if run["id"] not in labels:
            return index
    return 0


def mark(label: str | None) -> str:
    return {"good": "[good]", "bad": "[bad]"}.get(label or "", "[    ]")


def show_tool_calls(run: dict[str, Any]) -> None:
    calls = run.get("tool_calls") or []
    if not calls:
        st.caption("No tool calls.")
        return
    for call in calls:
        with st.container(border=True):
            st.markdown(f"**{call.get('name', 'tool')}**")
            st.json(call.get("arguments") or {})
            if call.get("error"):
                st.error(call["error"])
            if call.get("result_id"):
                st.caption(f"result_id: {call['result_id']}")


def show_response(run: dict[str, Any]) -> None:
    report = run.get("report") or ""
    if report:
        st.markdown(report)
        return
    if run.get("asked_fields") or run.get("asked_message"):
        fields = ", ".join(run.get("asked_fields") or [])
        st.info(f"Asked for: {fields}\n\n{run.get('asked_message', '')}")
        return
    if run.get("failure"):
        st.error(f"Failed closed: {run['failure']}")
        return
    if run.get("error"):
        st.error(f"Run error: {run['error']}")
        return
    st.warning("No response was recorded for this run.")


def main() -> None:
    st.set_page_config(page_title="Label Assay responses", layout="wide")
    st.title("Label Assay evaluation responses")

    if not RESULTS_FILE.exists():
        st.error(
            f"{RESULTS_FILE} not found. Build the consolidated results file first."
        )
        st.stop()

    if "runs" not in st.session_state:
        st.session_state.runs = load_results()
        st.session_state.labels = load_labels()
        st.session_state.idx = first_unlabeled(
            st.session_state.runs, st.session_state.labels
        )

    runs: list[dict[str, Any]] = st.session_state.runs
    labels: dict[str, dict[str, str]] = st.session_state.labels
    idx: int = st.session_state.idx
    if not runs:
        st.error("The results file is empty.")
        st.stop()
    idx = max(0, min(idx, len(runs) - 1))

    done = sum(1 for run in runs if run["id"] in labels)
    good = sum(1 for value in labels.values() if value.get("label") == "good")
    bad = sum(1 for value in labels.values() if value.get("label") == "bad")
    st.sidebar.progress(
        done / len(runs) if runs else 0.0, text=f"{done}/{len(runs)} labeled"
    )
    st.sidebar.write(f"good: {good} | bad: {bad}")

    categories: dict[str, int] = {}
    for value in labels.values():
        if value.get("label") == "bad":
            category = value.get("failure_category") or "(none)"
            categories[category] = categories.get(category, 0) + 1
    if categories:
        st.sidebar.caption("Failure categories")
        for category, count in sorted(categories.items(), key=lambda item: -item[1]):
            st.sidebar.write(f"- {category}: {count}")

    def option_label(index: int) -> str:
        run = runs[index]
        label = labels.get(run["id"], {}).get("label")
        return f"{mark(label)} {run['id']} {run['question'][:60]}"

    choice = st.sidebar.selectbox(
        "Jump to", list(range(len(runs))), index=idx, format_func=option_label
    )
    if choice != idx:
        st.session_state.idx = choice
        st.rerun()

    previous_col, next_col = st.sidebar.columns(2)
    if previous_col.button("Previous", disabled=idx == 0):
        st.session_state.idx -= 1
        st.rerun()
    if next_col.button("Next", disabled=idx >= len(runs) - 1):
        st.session_state.idx += 1
        st.rerun()

    if st.sidebar.button("Reload labels from disk"):
        st.session_state.labels = load_labels()
        st.rerun()

    st.sidebar.caption(f"Saving to `{LABELS_FILE.relative_to(ROOT)}`")

    run = runs[idx]
    key = run["id"]
    existing = labels.get(key, {})

    st.caption(
        f"{idx + 1}/{len(runs)} | {run['id']} | {run['type']} | "
        f"{run['category']} | status={run.get('status')} | "
        f"validation={run.get('validation_status')}"
    )

    st.header("Question")
    st.markdown(run["question"])

    st.header("Agent response")
    show_response(run)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Citations", run.get("citations", 0))
    metric_cols[1].metric("Tools", len(run.get("tool_calls") or []))
    metric_cols[2].metric("Latency (ms)", run.get("latency_ms") or 0)
    metric_cols[3].metric("Validation attempts", run.get("validation_attempts") or 0)

    with st.expander("Retrieved context and validation", expanded=True):
        st.subheader("Profile")
        st.json(run.get("profile") or {})
        st.subheader("Tool calls")
        show_tool_calls(run)
        if run.get("research_urls"):
            st.subheader("Research sources")
            for url in run["research_urls"]:
                st.markdown(f"- [{url}]({url})")
        st.subheader("Validation")
        mismatches = run.get("validation_mismatches") or []
        if mismatches:
            st.warning("\n".join(f"- {item}" for item in mismatches))
        else:
            st.success("No validation mismatches.")
        if run.get("report_raw"):
            with st.expander("Raw report with citation markers"):
                st.code(run["report_raw"], language="markdown")

    with st.expander("Rubric", expanded=done == 0):
        st.markdown(RUBRIC)

    st.divider()
    st.header("Decision")
    label = st.radio(
        "Is this response good?",
        LABEL_VALUES,
        index=LABEL_VALUES.index(existing["label"])
        if existing.get("label") in LABEL_VALUES
        else None,
        horizontal=True,
        key=f"label-{key}",
    )
    category_default = existing.get("failure_category", "")
    category_options = ["", *FAILURE_CATEGORIES]
    category = st.selectbox(
        "Failure category (only for bad responses)",
        category_options,
        index=category_options.index(category_default)
        if category_default in category_options
        else 0,
        disabled=label != "bad",
        key=f"cat-{key}",
    )
    comments = st.text_area(
        "Comments",
        value=existing.get("comments", ""),
        key=f"comments-{key}",
    )
    missing_category = label == "bad" and not category
    if missing_category:
        st.warning("Pick a failure category for a bad response.")

    def persist() -> None:
        labels[key] = {
            "id": key,
            "label": label or "",
            "failure_category": category if label == "bad" else "",
            "comments": comments,
            "labeled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        save_labels(labels)

    save_col, next_col = st.columns(2)
    if save_col.button(
        "Save and next",
        type="primary",
        disabled=label is None or missing_category,
    ):
        persist()
        order = list(range(idx + 1, len(runs))) + list(range(idx))
        next_index = next(
            (index for index in order if runs[index]["id"] not in labels), None
        )
        if next_index is None:
            st.success("All responses are labeled.")
        else:
            st.session_state.idx = next_index
            st.rerun()
    if next_col.button(
        "Save without moving",
        disabled=label is None or missing_category,
    ):
        persist()
        st.success(f"Saved {key}.")


main()
