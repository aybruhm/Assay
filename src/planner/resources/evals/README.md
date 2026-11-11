# Evaluation assets

This directory holds the Assay evaluation scenarios, results and human labels.

## Files

- `scenarios.csv`: 60 scenarios with `question`, `category` and `type`.
- `results/results-final.jsonl`: the consolidated run used by the labeler. It combines the full batch with the targeted post-fix, shorthand and research reruns.
- `results/results-final.csv`: the same consolidated results in table form.
- `labels.csv`: human labels with `id`, `label`, `failure_category`, `comments` and `labeled_at`.
- `analysis.md`: the evaluation results and the defects found.

## Label the responses

```sh
uv run streamlit run scripts/label_evals.py
```

The app shows the question, the full response, the extracted profile, the tool calls, the research sources, the validation result and the raw response with citation markers. It resumes at the first unlabeled response and saves to `labels.csv`.

## Rubric

Good responses answer with grounded figures, ask for a missing fact, fail closed, or decline an out-of-scope request. They state the material assumptions and never rank or select an option.

Bad responses use one of these categories:

- `hallucination`: an invented figure, rate, input, source or unsupported fact.
- `wrong-scope`: financial advice, a ranking, or an answer outside Assay's purpose.
- `incomplete`: a material assumption, option or limitation is missing.
- `incorrect-details`: wrong jurisdiction, tax year or misread fact.
- `formatting`: broken markdown or unreadable output.
- `other`: anything else that makes the response unusable.

## Current labels

The first labeling pass covers 26 responses: 22 good and 4 bad.

The failures are:

- `E018`, `E019` and `E031` are incomplete. The Nigeria take-home calculator applies an 8% employee pension contribution, but the response does not identify that as an assumption.
- `E003` has incorrect details. It claims Welsh rates match England and Wales without a Wales-specific source in the rule pack.

The most common failure category is `incomplete`.

## Correctness judge

`scripts/judge_evals.py` grades the labeled responses with structured output (`reasoning` and `label`) and compares the judge with `labels.csv`. See `judge/README.md` for the prompt versions, metrics and the fixed disagreement.

```sh
uv run python scripts/judge_evals.py --prompt v3
```
