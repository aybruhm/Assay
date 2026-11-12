# Assay correctness judge

`scripts/judge_evals.py` grades each labeled response with structured output. The judge returns two fields:

- `reasoning`: a step-by-step check of the question, the response and the tool context.
- `label`: `good` or `bad`.

The judge sees the question, the response, the extracted profile, the tool calls, the research sources and the validation result. It never sees the human label or the human comments, so the comparison is not contaminated by the answer it is supposed to predict.

The judge ran with `anthropic:claude-opus-5`. Set `JUDGE_MODEL` to pin a different model.

## Run

```sh
uv run python scripts/judge_evals.py --prompt v3
```

The script compares the judge labels with `labels.csv` and writes three files:

- `judge-results-v3.csv`
- `judge-results-v3.jsonl`
- `judge-summary-v3.json`

The `v1` and `v2` prompts and their result files are kept so that the iterations can be compared.

## Results

`bad` is the positive class, because the failures are what matter.

| Prompt | Accuracy | Precision | Recall | TP | FP | FN | TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.692 | 0.000 | 0.000 | 0 | 4 | 4 | 18 |
| v2 | 0.962 | 0.800 | 1.000 | 4 | 1 | 0 | 21 |
| v3 | 1.000 | 1.000 | 1.000 | 4 | 0 | 0 | 22 |

## v1 disagreements

V1 missed every failure, and it also flagged four good responses. The false negatives, where the judge said good and the human said bad, were:

- `E003`: it accepted the claim that Welsh rates match England and Wales.
- `E018`, `E019` and `E031`: it accepted the Nigeria pension deduction as a stated assumption.

The false positives, where the judge said bad and the human said good, were:

- `E036`: it expected the agent to convert a monthly salary into annual pay.
- `E045`: it thought the full available dividend was invented because no tool call passed that amount explicitly.
- `E054` and `E060`: it treated a missing-field clarification for the country as malformed output.

## v2 changes

The second prompt adds guidance taken directly from those disagreements:

- The Nigeria `take_home` calculator always applies an 8% employee pension contribution. Showing the deduction is not the same as saying it was assumed.
- The GB rule pack has no Wales-specific rate. A claim that Welsh rates match England without a Wales-specific source is `incorrect-details`.
- Assay must not convert monthly, weekly, hourly or daily amounts into annual figures. Asking for the annual figure is a good response.
- A validation status of `passed` means every figure matched a calculator result. A `dividend_capacity` call without `dividend_amount` computes the full available dividend, so those figures are not invented.
- Asking for a missing required field is a valid clarifying question, even when the question is only the field name.

The judge payload also now presents an asked response as a question for the missing fields, rather than as an empty field list.

## v3 change

A later run of v2 produced one false positive on `E020`. The response said that the England, Wales and Northern Ireland rates apply. That is a generic GB rate statement, not a claim about Welsh rates. V3 adds this clarification to the prompt: "A generic statement that the England, Wales and Northern Ireland rates apply is acceptable when the user asked about England and the rule pack is GB; do not treat that as a Wales-specific claim." V3 restored accuracy to 1.000.

## The fixed example: E018

The human label is bad, with the category `incomplete`.

V1 said good. It listed the pension line in the response and concluded that the material assumptions had been stated, because the response itemised the pension deduction and the rent relief.

V2 said bad. It reasoned that the user never mentioned a pension, that the response shows an 8% pension deduction, and that the response never says the deduction was assumed. Showing the number is not the same as identifying it as an assumption.

The outcome changed from a false negative to a true positive. That is the kind of disagreement the judge prompt is meant to learn from.

## Caveat

The validation set has 26 labeled responses. I improved v2 and v3 against the disagreements in that same set, so perfect agreement here is not a guarantee on a holdout set. Run the judge again when new labels are added or when the agent prompt changes.
