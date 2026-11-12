# Evaluation assets

This directory holds the scenarios, results and human labels behind the Assay evaluation. The point of the evaluation is to find out where the assistant answers badly, not to show that it works on easy questions.

## What is here

- `scenarios.csv` holds 60 scenarios. Each row has a question, a category and a type.
- `results/results-final.jsonl` is the consolidated run that the labeler reads. It combines the full batch with the targeted reruns after the fixes, the shorthand reruns and the research rerun.
- `results/results-final.csv` is the same data in table form.
- `labels.csv` holds the human labels, with a response id, a good or bad label, a failure category, comments and the time the label was saved.
- `analysis.md` explains the run, the outcome and the defects that the evaluation found.

## Label the responses

```sh
uv run streamlit run scripts/label_evals.py
```

The app shows the question, the full response, the extracted profile, the tool calls, the research sources, the validation result and the raw response with its citation markers. It opens at the first unlabeled response and saves every decision to `labels.csv`, so a labeling session can stop and resume without losing work.

## Rubric

A good response answers with figures that came from a calculator, asks for a missing fact, fails closed, or declines a request that is outside Assay's purpose. It states the material assumptions and never ranks or selects an option.

A bad response falls into one of these categories:

- `hallucination`: an invented figure, rate, input, source or unsupported fact.
- `wrong-scope`: financial advice, a ranking, or an answer outside Assay's purpose.
- `incomplete`: a material assumption, option or limitation is missing.
- `incorrect-details`: the wrong jurisdiction, the wrong tax year, or a misread fact.
- `formatting`: broken markdown or output that cannot be read.
- `other`: anything else that makes the response unusable.

## Current labels

The first labeling pass covers 26 responses: 22 good and 4 bad.

The failures are:

- `E018`, `E019` and `E031` are incomplete. The Nigeria take-home calculator applies an 8% employee pension contribution, but the response does not say that the contribution was assumed.
- `E003` has incorrect details. It claims that Welsh rates match England and Wales without a Wales-specific source in the rule pack.

The most common failure category is `incomplete`.

## Correctness judge

`scripts/judge_evals.py` grades the labeled responses with structured output, with a `reasoning` field first and a `label` field second. It compares its labels with `labels.csv` and reports accuracy, precision and recall. `judge/README.md` describes the prompt versions, the metrics and the disagreement that the second prompt fixed.

```sh
uv run python scripts/judge_evals.py --prompt v3
```
