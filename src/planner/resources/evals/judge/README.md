# Assay correctness judge

`scripts/judge_evals.py` grades each labeled response with structured output:

- `reasoning`: a step-by-step check of the question, response and tool context.
- `label`: `good` or `bad`.

The judge sees the question, response, extracted profile, tool calls, research sources and validation result. It never sees the human label or comments.

The judge ran with `anthropic:claude-opus-5`. Set `JUDGE_MODEL` to pin a different judge model.

## Run

```sh
uv run python scripts/judge_evals.py --prompt v3
```

The script compares the judge labels with `labels.csv` and writes:

- `judge-results-v3.csv`
- `judge-results-v3.jsonl`
- `judge-summary-v3.json`

`v1` and `v2` are kept so the prompt iterations can be compared.

## Results

`bad` is the positive class.

| Prompt | Accuracy | Precision | Recall | TP | FP | FN | TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.692 | 0.000 | 0.000 | 0 | 4 | 4 | 18 |
| v2 | 0.962 | 0.800 | 1.000 | 4 | 1 | 0 | 21 |
| v3 | 1.000 | 1.000 | 1.000 | 4 | 0 | 0 | 22 |

## v1 disagreements

False negatives, where the judge said good but the human said bad:

- `E003`: accepted the claim that Welsh rates match England and Wales.
- `E018`, `E019`, `E031`: accepted the Nigeria pension deduction as a stated assumption.

False positives, where the judge said bad but the human said good:

- `E036`: expected the agent to convert a monthly salary to annual pay.
- `E045`: thought the full available dividend was invented because no tool call passed that amount explicitly.
- `E054`, `E060`: treated the missing-field clarification for country as malformed output.

## v2 changes

The second prompt adds guidance from the disagreements:

- The Nigeria `take_home` calculator always applies an 8% employee pension contribution. Showing the deduction is not the same as saying it was assumed.
- The GB rule pack has no Wales-specific rate. A claim that Welsh rates match England without a Wales-specific source is `incorrect-details`.
- Assay must not convert monthly, weekly, hourly or daily amounts to annual figures. Asking for the annual figure is good.
- Validation `passed` means every figure matched a calculator result. A `dividend_capacity` call without `dividend_amount` computes the full available dividend.
- Asking for a missing required field is a valid clarifying question, even when the message is only the field name.

The judge payload also now presents an asked response as a question for the missing fields rather than an empty field list.

## v3 change

A rerun of v2 after the whitespace cleanup produced one false positive on `E020`. The response said "the England, Wales and Northern Ireland rates apply," which is a generic GB rate statement, not a Wales-specific claim. V3 adds this clarification: "A generic statement that the England, Wales and Northern Ireland rates apply is acceptable when the user asked about England and the rule pack is GB; do not treat that as a Wales-specific claim." V3 restored 1.000 accuracy.

## Fixed example: E018

Human label: bad, `incomplete`.

v1 said good. It listed the pension line and concluded that the material assumptions were stated, because the response itemised the pension deduction and the rent relief.

v2 said bad. It reasoned that the user never mentioned a pension, the response shows an 8% pension deduction, and the response never says that the deduction was assumed. Showing the number is not the same as identifying it as an assumption.

Outcome changed from `FN` to `TP`.

## Caveat

The validation set has 26 labeled responses. V2 was improved against the disagreements in that set, so perfect agreement here is not a guarantee on a holdout set. Re-run the judge when new labels are added or the agent prompt changes.
