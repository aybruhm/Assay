# Assay

Assay is a conversational financial planning assistant. It currently supports questions from users in the United Kingdom and Nigeria. It answers financial questions with figures from deterministic calculators, and a validator checks every displayed figure against a calculator result before the response is delivered.

The tax thresholds and rates live in rule packs, which are versioned YAML files. Each value cites the official country page or an accredited source. The agent chooses the tools, asks for missing facts, and explains the results. It never supplies a tax rate that did not come from an official source.

## What it can answer today

- What do I take home now?
- What do I take home if I pay more into my pension?
- For a company director, how does salary compare with dividends?
- I have a PAYE salary. How much can my company pay me in dividends, and what tax is due?
- What do the same savings come to in an ISA against a general account?
- What is my income tax on salary, pension, rental and other income?
- How much student loan will I repay?
- What is the basic rate, the personal allowance, or another rule value?

## Demo

A real-model run:

```sh
PLANNER_DB_URL=postgresql://planner:planner@localhost:5432/planner \
PLANNER_MODEL=anthropic:claude-opus-5 \
PLANNER_FAKE_SINK=1 \
uv run python -m planner.cli run demo \
  "I earn £45,000 a year and live in England. What is my take-home pay?" \
  --date 2026-10-18
```

```text
Your annual take-home pay is £35,919.60.

Here is how that figure is reached, based on England rates for the 2026 planning date:

| Item | Amount |
|---|---|
| Gross annual pay | £45,000.00 |
| Personal allowance | £12,570.00 |
| Taxable income | £32,430.00 |
| Income tax | £6,486.00 |
| National Insurance | £2,594.40 |
| Take-home (net) pay | £35,919.60 |

Figures:

Figure                  Amount
------------------  ----------
Net pay             £35,919.60
Gross annual        £45,000.00
Personal allowance  £12,570.00
Taxable income      £32,430.00
Income tax           £6,486.00
National insurance   £2,594.40
```

Run the same flow without an API key:

```sh
PLANNER_DB_URL=postgresql://planner:planner@localhost:5432/planner \
PLANNER_FAKE_MODEL=1 \
PLANNER_FAKE_SINK=1 \
uv run python -m planner.cli run demo \
  "I earn 45,000 a year in England" \
  --date 2026-10-18
```

The scripted model produces the same figures with a simpler explanation. The report is printed only after validation, so the demo never exposes an unvalidated draft.

The labeler is a third way to see the project. Run `uv run streamlit run scripts/label_evals.py` to open the question, the full response, the tool context and the good or bad controls without an API key.

## Why I built it

General-purpose AI assistants are bad with money. They invent numbers, apply last year's rates or another country's rules, and slip from explaining trade-offs into telling you what to do. I wanted an assistant that answers the question, shows the figures, and refuses to answer when it cannot ground them.

Assay is also a portfolio project about correctness for LLM systems. The repository has 370 tests, a 60-scenario evaluation set, 26 human-labeled responses, an LLM judge with structured output, Phoenix traces and a Provenance audit trail. The demo and evaluation sections are the fastest way to see that.

## What goes wrong, and what Assay does about it

| Failure | Response |
| --- | --- |
| The model invents a number | Models do not calculate. They call a calculator that produces the figures. |
| The model applies the wrong year's rates | Rates and thresholds are data in YAML rule packs, each value carrying a source URL. |
| A figure cannot be checked | Every figure in the report names the result id it came from. |
| The model invents an input | Profile facts come from the extracted profile, not from model-supplied tool arguments. |
| An option is presented as a recommendation | The narrator lists every option the tool results support and describes each one without ranking it. The validator rejects recommendation language and any figure without a result marker. |

If the model cannot answer, the run returns no figures and states the reason. It does not guess.

## How a run works

The graph is an agent loop, not a fixed list of questions.

```mermaid
flowchart TD
    Start([start]) --> intake[intake: extract the country and known facts]
    intake -->|country missing| ask[ask_user: pause and ask]
    intake -->|country known| prepare[prepare: load the rule pack]
    prepare --> agent[agent: choose a tool or answer]
    agent -->|tool call| tools[tools: run a calculator or research tool]
    tools --> agent
    agent -->|missing input| ask
    ask -->|answer| intake
    agent -->|enough results| narrate[narrate: explain the figures]
    narrate --> validate[validate: check every figure and the wording]
    narrate -->|rule pack changed| fail
    validate -->|passed| deliver[deliver: write the audit record, end]
    validate -->|figures or wording wrong, retry| narrate
    validate -->|too many retries| fail[fail_closed: end with no figures]
    prepare -->|unsupported country or date| fail
    deliver -->|audit write failed| fail
```

- **Intake** extracts the country and any facts the user stated, including an answer collected by `ask_user`. Country and planning date select the rule pack.
- **Prepare** loads the pack and fails closed when the country or date is not supported.
- **Agent** reads the conversation, the profile, the tool catalog and the results so far. It either calls tools, asks for a missing input, or says it has enough results.
- **Tools** run calculators or trusted-source research. A calculator result carries its name, version, inputs and rule ids. A research result carries its title, URL and fetch time.
- **Narrate** writes the answer from the tool results. Every figure is copied with a citation marker.
- **Validate** recomputes every displayed figure and rejects wrong numbers, unknown ids, uncited figures or recommendation language. After three attempts the run ends with no figures.
- **Deliver** writes the audit record. No audit record, no delivery. The audit gateway can also refuse a record, which withholds the report.

The model can call more than one tool. It can compute take-home pay for an existing salary and then use that salary in a dividend calculation. It can also stop and ask for a missing fact.

## Tools

| Tool | What it does |
| --- | --- |
| `take_home` | Income tax and net pay for a salary. GB includes National Insurance; NG returns PAYE. |
| `income_tax` | Income tax and net income for salary, pension, rental and other non-dividend income. |
| `pension` | Take-home pay with a pension contribution that reduces taxable pay. |
| `student_loan` | Annual student loan repayment for Plan 1, Plan 2, Plan 4, Plan 5 or Postgraduate. |
| `director_pay` | Salary and dividend mix compared with the same company cost paid as salary. |
| `dividend_capacity` | Dividend available from company profit and reserves, dividend tax, and net dividend. |
| `isa_vs_general` | After-tax growth of the same savings in an ISA and a general account. |
| `lookup_rule` | A rate or threshold with its effective date and official source. Works for GB and NG. |
| `search_trusted_sources` | Titles, URLs and snippets from allowlisted trusted pages. |
| `fetch_source` | The cleaned text of one allowlisted trusted page. |

Calculator tools read the rule pack for the run's country and planning date. Research tools read allowlisted pages. The model sees the tool names, arguments and supported jurisdictions. The tool executor checks the arguments against a Pydantic model before it runs anything.

`take_home` supports GB and NG. The other calculators are GB only. `lookup_rule` and the research tools work for both.

## Evaluation

I wrote 60 scenarios across happy paths, phrasing variants, edge cases, out-of-scope requests and breaking prompts.

| Type | Count |
| --- | ---: |
| Happy path | 20 |
| Varied phrasing | 11 |
| Edge case | 14 |
| Out of scope | 7 |
| Breaking | 8 |
| Total | 60 |

I ran the full batch against `anthropic:claude-opus-5`. It passed 51, reviewed 7 and failed 2. The failures were real. Rule lookup rejected the rule-pack source URL, the model did not use the Nigeria calculator, the model invented distributable reserves, and shorthand amounts such as `45k` failed inside the tools. I fixed those and reran the affected cases. The combined result is 60 pass, 0 review and 0 fail. The only full-batch search failure was a transient DuckDuckGo outage, and the rerun passed.

| Run | Pass | Review | Fail |
| --- | ---: | ---: | ---: |
| Full batch | 51 | 7 | 2 |
| Combined after targeted reruns | 60 | 0 | 0 |

I labeled 26 responses by hand: 22 good and 4 bad. Three were incomplete because the Nigeria take-home answer showed an 8% pension deduction without saying it was assumed. One had incorrect details because it claimed Welsh rates match England without a Wales-specific source.

| Failure category | Count | Pattern |
| --- | ---: | --- |
| `incomplete` | 3 | The Nigeria take-home response shows an 8% employee pension deduction without saying it was assumed. |
| `incorrect-details` | 1 | The Wales response claims Welsh rates match England without a Wales-specific source. |

The judge is an LLM with structured output: reasoning first, then a `good` or `bad` label. It sees the question, response, profile, tool calls, sources and validation, but not the human label. I iterated it from v1 to v3. V1 missed both failure patterns and over-flagged four good responses. V2 added the patterns, and v3 clarified that a generic England, Wales and Northern Ireland rate statement is not a Wales-specific claim. V3 agrees with all 26 labels. `bad` is the positive class.

| Prompt | Accuracy | Precision | Recall | TP | FP | FN | TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 | 0.692 | 0.000 | 0.000 | 0 | 4 | 4 | 18 |
| v2 | 0.962 | 0.800 | 1.000 | 4 | 1 | 0 | 21 |
| v3 | 1.000 | 1.000 | 1.000 | 4 | 0 | 0 | 22 |

The label set is small, so perfect agreement on these 26 responses is not a guarantee on a holdout set. The Nigeria pension wording is still a content issue: the judge catches it, but the narrator should say the deduction was assumed.

The scenarios, analysis, labels and judge report are in `src/planner/resources/evals/`. The labeler runs without an API key. The judge needs an Anthropic key. The consolidated results are in `src/planner/resources/evals/results/results-final.jsonl`.

## Monitoring

Every CLI command calls `configure_tracing()` from `src/planner/telemetry.py`, which registers a Phoenix tracer with auto-instrumentation. The traces show model calls, tool calls, validation attempts and delivery. Set `PHOENIX_PROJECT_NAME` and `PHOENIX_COLLECTOR_ENDPOINT` to point at a collector. With no endpoint set, traces go to `http://localhost:6006`.

I look for the graph nodes in order, the tool arguments and result ids, validation mismatches, and the fail-closed path when a country, date or input is unsupported.

The `deliver` node writes one audit event per step through the Provenance sink. A blocked or failed audit write withholds the report. With `PLANNER_FAKE_SINK=1`, events stay in memory; with a configured gateway, they go to the audit log. The policy Assay expects is `src/planner/resources/policies/assay_planner_policy.json`.

## Architecture overview

- **The graph** (`src/planner/graph/`) is the runtime: intake, the agent loop, validation, delivery and checkpoints.
- **The tools** (`src/planner/tools/`) map tool calls to calculators, rule packs and trusted-source research. The agent node never imports a calculator.
- **The rule packs** (`rules/gb/*.yaml`, `rules/ng/*.yaml`) are data, not code. A reviewer can check any value against its source URL without reading code.

| Port | Adapters |
| --- | --- |
| `ModelPort`: `extract_profile`, `decide`, `narrate` | `LangChainModel` (a real model) and `ScriptedModel` (fixed answers for tests) |
| `ResearchPort`: `search`, `fetch` | `HttpResearch` (trusted sources only) and `FakeResearch` (for tests) |
| `AuditSink`: `record_batch` | `ProvenanceSink` (the audit gateway) and `InMemorySink` (for tests) |

Money is a plain `int` at a fixed scale of 10⁴ (£142,382.3234 is `1423823234`). No floats, and every rounding step is explicit and named. Countries are packages behind one small contract plus one line in a registry. The United Kingdom (`GB`) provides the calculator tools. Nigeria (`NG`) provides `take_home`. Both countries support `lookup_rule`.

## Rule packs and money

Rule packs are versioned YAML files in `rules/`. Each rule has an id, kind, value, effective date, source URL and `checked_on` date. The GB pack for 2026-27 is `rules/gb/2026-27.yaml`. Nigeria uses `rules/ng/2026.yaml`.

Do not invent or hard-code tax values. Add or change them in the rule pack and record the source and the date checked. The validator uses the rule pack's currency and the calculator's display mode, so a new country does not need new formatting code.

## Running it

You need Python 3.14, [uv](https://docs.astral.sh/uv/), and Docker for PostgreSQL.

```sh
uv sync --all-groups
docker compose up -d db
export PLANNER_DB_URL=postgresql://planner:planner@localhost:5432/planner
```

Run the scripted demo without an API key:

```sh
PLANNER_FAKE_MODEL=1 PLANNER_FAKE_SINK=1 \
  uv run python -m planner.cli run demo \
  "I earn 45,000 a year in England" \
  --date 2026-10-18
```

Run with a real model by setting `PLANNER_MODEL` instead of `PLANNER_FAKE_MODEL`:

```sh
PLANNER_MODEL=anthropic:claude-opus-5 \
PLANNER_FAKE_SINK=1 \
uv run python -m planner.cli run demo \
  "I earn £45,000 a year and live in England. What is my take-home pay?" \
  --date 2026-10-18
```

Add `--stream` to `run` or `resume` to print each graph node to stderr as it finishes. The report is still printed only after validation, so progress streaming never exposes an unvalidated draft.

`planner run` appends the message to the thread and keeps the profile. Use `planner history <thread>` to inspect checkpoints and `planner resume <thread>` to continue a paused or crashed run.

The CLI loads `.env` from the repo root at startup, and variables set in your shell take precedence. Copy the template and fill in your values:

```sh
cp .env.template .env
```

### Configuration

Three variables have no default. A run fails when one is missing:

| Variable | What it does |
| --- | --- |
| `PLANNER_DB_URL` | PostgreSQL connection string for checkpoints. |
| `PLANNER_MODEL` | LangChain model name for the real model adapter. |
| `PROVENANCE_GATEWAY_URL` | Provenance API base URL, including `/api` (for example `https://<PROVENANCE_HOST>/api`). The client appends `/v1/gateway/execute`. |

The fake adapters replace two of them. Set `PLANNER_FAKE_MODEL` instead of `PLANNER_MODEL` to run without an API key, and `PLANNER_FAKE_SINK` instead of `PROVENANCE_GATEWAY_URL` to keep audit records in memory.

With a real model, set `ANTHROPIC_API_KEY` in `.env` or the shell. The scripted model does not need it.

The rest are optional:

| Variable | Default | What it does |
| --- | --- | --- |
| `PLANNER_FAKE_MODEL` | unset | Any non-empty value uses the scripted in-memory model. |
| `PLANNER_FAKE_SINK` | unset | Any non-empty value writes audit records to memory. |
| `PLANNER_FAKE_RESEARCH` | unset | Any non-empty value uses the in-memory research adapter. |
| `PLANNER_RESEARCH_TIMEOUT` | `10` | Timeout in seconds for research requests. |
| `PLANNER_RESEARCH_USER_AGENT` | `Assay/0.1 (trusted source research)` | User agent sent when fetching trusted pages. |
| `PLANNER_RULES_DIR` | `rules/` in the repo | Directory the rule packs load from. |
| `PLANNER_CRASH_AT` | unset | Kill the process as the named graph node starts. Used by the resume demo. |
| `PROVENANCE_AGENT_ID` | `planner` | Agent identity sent to the audit gateway. |
| `PROVENANCE_API_KEY` | unset | API key for the audit gateway. Its scope selects the policy that judges every audit event. |
| `PHOENIX_PROJECT_NAME` | `assay` | Phoenix project that receives the traces. |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Phoenix collector base URL. |
| `PHOENIX_API_KEY` | unset | API key for a hosted Phoenix collector. |

The CLI calls `configure_tracing()` on every command. It loads `.env`, then registers a Phoenix tracer with auto-instrumentation. The Phoenix SDK reads `PHOENIX_COLLECTOR_ENDPOINT` and `PHOENIX_API_KEY` itself, so this project does not pass them explicitly.

## Audit policy

When a run is delivered, Assay sends one audit event per step to the [Provenance](https://github.com/aybruhm/provenance) gateway. Provenance checks each event against a policy before it records it. The policy Assay expects is `src/planner/resources/policies/assay_planner_policy.json`.

Rules run top to bottom, and the first rule that returns a decision wins.

| Event | Decision |
| --- | --- |
| `planner.rule_pack_loaded` | Block when the jurisdiction is not `GB` or `NG`. Otherwise record. |
| `planner.approval` | Block when an approval event says `approved` is false. The event is only sent when human approval is enabled. |
| `planner.research`, `planner.calculation`, `planner.validation`, `planner.delivery` | Record. |
| Anything else | Block. |

A blocked event withholds the report. The deliver step treats a refused audit record like a failed one: the run ends in `fail_closed` with no figures. The jurisdiction rule is a release gate, not a logging filter. A report built on an unsupported rule pack is never shown to the user. The approval rule applies only when an approval event is sent. The default delivery path uses the validator's compliance check instead.

The sink sends `decision=ALLOW` with every event, but the gateway ignores it and uses the policy's result. With no policy assigned to the API key's scope, the gateway blocks every event, so no report is delivered. Unknown events are blocked by the final rule. A blocked run still leaves a trail: the sink sends all events of a run at once, and the blocked event is recorded with its reason.

To configure it, use the Provenance UI or the API calls below. Policy management needs a signed-in Provenance user.

1. Create the policy. Send the contents of `src/planner/resources/policies/assay_planner_policy.json` as the body of `POST /api/v1/policies/`. Note the returned policy id.
2. Assign it to Assay's tenant with `POST /api/v1/policies/<POLICY_ID>/assign` and the body `{"tenant_id": "<TENANT_ID>"}`. The response contains a `tenant_policy_id`.
3. Create an API key with `POST /api/v1/api_keys/` and the body `{"user_id": "<USER_ID>", "scope_id": "<TENANT_POLICY_ID>"}`. The scope ties the key to this policy.
4. Set the key and gateway in `.env`:

   ```sh
   PROVENANCE_GATEWAY_URL=https://<PROVENANCE_HOST>/api
   PROVENANCE_API_KEY=<API_KEY_FROM_STEP_3>
   ```

The default local path uses `PLANNER_FAKE_SINK=1`, so the audit events stay in memory.

## Tests

```sh
uv run pytest src/planner/tests -q
uv run mypy src/planner
uv run lint-imports
```

The full suite needs PostgreSQL for the integration tests. It covers calculators, graph nodes, validation, provenance, research, audit delivery, resume and streaming.

The import contracts enforce the trust boundary:

- LLM nodes never import calculators.
- Calculators never import the LLM client or the graph.
- Jurisdiction packages never import each other.

## License

See [LICENSE](LICENSE).
