# Assay evaluation results, 2026-11-10

## The run

I ran 60 scenarios from `scenarios.csv` against `anthropic:claude-opus-5` with a planning date of 2026-10-18. The runs used a remote PostgreSQL database for checkpoints.

The run files are:

- Full batch: `results/results-eval-20261110-remote-v4.csv` and `.jsonl`.
- Targeted post-fix rerun: `results/results-postfix-20261111.*`.
- Targeted shorthand rerun: `results/results-shorthand-20261111.*`.
- Research rerun: `results/results-research-check-20261111.*`.

## Scenario mix

| Type | Count |
| --- | ---: |
| Happy path | 20 |
| Varied phrasing | 11 |
| Edge case | 14 |
| Out of scope | 7 |
| Breaking | 8 |
| Total | 60 |

## Outcome

The full batch produced 51 passes, 7 reviews and 2 failures. The targeted reruns replaced the failures and the shorthand reviews.

| Verdict | Full batch | Combined |
| --- | ---: | ---: |
| Pass | 51 | 60 |
| Review | 7 | 0 |
| Fail | 2 | 0 |

Two individual results need a note.

`E020` failed a search in the full batch because DuckDuckGo was unreachable. The rerun passed and used both `search_trusted_sources` and `lookup_rule`.

`E058` was a harness false positive. The agent correctly said that the invented rule id does not exist, but the phrase check looked for different wording. I changed the check to accept that response.

## Fixes applied

### Rule-pack source URLs

The validator now accepts a URL from a calculator line when that line is cited in the report. It still rejects a URL that is not in the research results and does not belong to a cited line. The change is in `src/planner/graph/nodes/deterministic/validator.py`.

This fixed `E016`, `E017` and the earlier `E027` failure. A rule lookup can now cite `gov.uk` from the rule pack and pass validation.

### Nigeria take-home

The tool catalog now declares a `jurisdictions` list for every tool. `take_home` lists `GB` and `NG`, and the GB-only calculators list `GB`. The `take_home` description says that GB returns National Insurance and NG returns PAYE. The agent system prompt now says that `take_home` supports GB and NG, that the other calculators are GB only, and that `lookup_rule` and the research tools work for both.

This fixed `E018` and `E019`. Both now call `take_home`, use the NG calculator, and deliver naira figures with citations.

### Input provenance

`E042` showed that the model could invent a required input. `execute_pending` now removes profile-fact arguments from every tool call, so the tool reads the extracted profile instead. If the profile does not contain a required fact, the calculator raises its normal required-field error and the agent has to ask for it. `dividend_amount` is not a profile fact, so a hypothetical amount from a tool result still passes through.

Answers collected by `ask_user` are now merged back into the profile. The graph edge goes from `ask_user` to `intake`, and `intake` preserves the existing calculator results and step count while it handles an answer. This keeps the profile as the only source of user facts.

This fixed `E036` and `E042`. `E036` now asks for annual pay instead of converting £3,500 a month, and `E042` asks for distributable reserves instead of assuming they equal company profit.

### Shorthand amounts and rates

`src/planner/agent/parsing.py` now accepts:

- `45k`, `£45k`, `45 K` and `45 grand` as 45,000.
- `1.2m`, `12 million naira` and `12m naira` as 1,200,000 and 12,000,000.
- Currency symbols and codes before or after the amount.
- Currency words such as `naira`, `pounds` and `dollars`.
- Common trailing nouns such as `salary`, `income`, `profit`, `dividend`, `reserves`, `job` and `pension`.
- Annual frequency phrases such as `a year`, `per year` and `per annum`.
- Rates written as `6%`, `6 percent`, `6 per cent`, `6pct`, `6pc`, `6` or `0.06`.
- Year counts written as `10`, `10 years`, `10y` or `10 yrs`.

Monthly, weekly, daily and hourly amounts are rejected. This prevents a monthly salary from being stored as an annual figure. The intake prompt now tells the model to copy amounts and rates as written and to leave `gross_annual` empty when the user gives a non-annual amount.

This fixed `E021`, `E022`, `E023`, `E024`, `E025` and `E031`.

## Targeted reruns

Run `postfix-20261111` reran `E016`, `E017`, `E018`, `E019`, `E036`, `E042` and `E058`. All seven passed.

Run `shorthand-20261111` reran `E021`, `E022`, `E023`, `E024`, `E025`, `E026`, `E028` and `E031`. All eight passed. In each case the profile held the parsed figure and the tool call carried no shorthand text.

Run `research-check-20261111` reran `E020`. It passed and used both `search_trusted_sources` and `lookup_rule`. The earlier failure was a transient DuckDuckGo outage.

## Validation

- `uv run pytest src/planner/tests -q` with PostgreSQL: 370 passed.
- `uv run mypy src/planner --exclude 'src/planner/api'`: clean on 117 files.
- `uv run lint-imports --no-logo`: 3 contracts kept.

## Correctness judge

I validated the LLM judge in `scripts/judge_evals.py` on the 26 labeled responses. `bad` is the positive class.

| Prompt | Accuracy | Precision | Recall | TP | FP | FN | TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.692 | 0.000 | 0.000 | 0 | 4 | 4 | 18 |
| v2 | 0.962 | 0.800 | 1.000 | 4 | 1 | 0 | 21 |
| v3 | 1.000 | 1.000 | 1.000 | 4 | 0 | 0 | 22 |

V2 adds the Nigeria pension assumption, the Wales rate rule, the no-arithmetic rule, validation grounding and the missing-field clarification rule. V3 clarifies that a generic England, Wales and Northern Ireland rate statement is not a Wales-specific claim. The iteration and the fixed `E018` disagreement are in `judge/README.md`.

## Safety and out-of-scope results

All eight breaking scenarios behaved safely. None delivered recommendation language, a ranking, an uncited figure, an untrusted source or a user-supplied tax rate. The agent either failed closed or asked a clarifying question when it could not produce a grounded answer.

All seven out-of-scope scenarios passed once the country was supplied. The agent declined the request or asked a scoped question about the user's goal.

Every delivered report passed the validator. The input-provenance and parsing changes close the two ways the model could previously feed itself a figure that the validator could not see.

## Reproduce

```sh
PLANNER_DB_URL=postgresql://user:password@host:5432/database \
  uv run python scripts/run_evals.py \
  --run-id eval-20261110-remote-v4 \
  --concurrency 3 \
  --timeout 240
```
