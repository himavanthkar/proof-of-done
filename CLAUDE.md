# Proof of Done

Built at The Recursive Agents Hackathon (Crusoe x Cerebral Valley), Shack15, San Francisco, Saturday Oct 17 2026.
Track: **Done Means Done**. Every line of code in this repo is written today.

## Pitch (keep this framing everywhere)

Agents fill vague goals with their own assumptions and then confidently report success.
Proof of Done is an agent team on Crusoe Managed Inference that turns a one-line goal into locked acceptance tests,
builds the code, stress-tests those tests by deliberately breaking the code (mutation testing), and has a verifier
from a different model family (Nemotron) check everything in a sandbox before it is allowed to say "done".
Every run ends with a receipt containing the evidence. We measure the false "done" rate on benchmark tasks with
hidden tests and compare it against an agent working alone and an agent checking its own work.

## Hard deadlines (Pacific time)

| Time | What |
|---|---|
| 12:15 PM | M0: Crusoe + verifier calls working |
| 1:30 PM | M1: full pipeline works end to end on one task |
| 2:30 PM | M2: mutation testing, retry, re-plan, ask-human all working |
| 3:30 PM | M3: eval harness run on all conditions, results table + chart |
| 4:05 PM | M4: demo.py polished, README done. CODE FREEZE |
| 4:15 PM | Human records the 1-minute video |
| 5:00 PM | Submission closes |

If anything blocks for more than 15 minutes, take the simpler fallback and move on. Working beats complete.

## Hackathon rules that affect the code

- Repo must be PUBLIC. Create `.gitignore` first. Never commit `.env`, keys, or `runs/cache/`.
- Judges must see only what was built today. README must list every component as built today.
- Banned: Streamlit, any project where a dashboard is the main feature, basic RAG. The demo is a terminal CLI using `rich`. The results chart is supporting evidence only.
- The agent team must run on Crusoe Managed Inference.

## Step 0: learn the Crusoe API from the official repo (do this first)

```bash
git clone --depth 1 https://github.com/crusoecloud/crusoe-developer-hub /tmp/crusoe-hub
ls /tmp/crusoe-hub/examples/hackathons/crusoe-cv-recursive-agents-hackathon
```

Read everything in that folder. Find: base URL, auth header format, exact model ids available, whether the API is
OpenAI-compatible, rate limits, logprobs support, and any helper code. Write findings to `NOTES.md`.
Check whether any Nemotron model is hosted on Crusoe.
If anything is still missing, ask the user ONE message containing all questions together.

## Models and roles (all configurable via env vars)

| Role | Env vars | Guidance |
|---|---|---|
| Spec agent | `SPEC_MODEL` | Strongest coding/reasoning model on Crusoe |
| Builder | `BUILDER_MODEL` | A smaller model on Crusoe that fails sometimes. We need real failures to catch. |
| Mutator | `MUTATOR_MODEL` | Same as spec is fine |
| Verifier | `VERIFIER_MODEL`, `VERIFIER_BASE_URL`, `VERIFIER_API_KEY` | Nemotron. Use Crusoe if hosted there, otherwise NVIDIA API (`https://integrate.api.nvidia.com/v1`). MUST be a different model family from the builder. |

`.env.example`:

```
CRUSOE_BASE_URL=
CRUSOE_API_KEY=
SPEC_MODEL=
BUILDER_MODEL=
MUTATOR_MODEL=
VERIFIER_BASE_URL=
VERIFIER_API_KEY=
VERIFIER_MODEL=
SANDBOX=local            # local | openshell
MUT_THRESHOLD=0.8
MAX_RETRIES=2
MAX_LLM_CALLS_PER_TASK=14
EVAL_N=30
EVAL_SEED=17
CONCURRENCY=6
```

## Architecture

```
one-line goal
   -> Spec agent: assumptions + pytest tests  (tests LOCKED: sha256 stored, builder cannot edit)
   -> Builder: solution.py
   -> Sandbox: run tests
        fail -> feedback to builder (RETRY)
        pass -> Mutation check: make mutants of solution, run tests on each
                 kill rate < MUT_THRESHOLD -> Spec agent sees surviving mutants, adds tests (1 round max),
                                              tests re-locked, change logged in receipt
   -> Verifier (different family): goal, assumptions, code, tests, results, mutation summary -> JSON verdict
   -> Decision step (plain Python, not an LLM): DONE | RETRY | REPLAN | ASK_HUMAN
   -> Receipt (JSON + rich panel)
```

### Agent contracts (all agents return JSON; parser must tolerate code fences)

**Spec agent**
- Input: goal text (plus a signature if the task provides one).
- Output: `{"function_name", "signature", "assumptions": [..], "tests": "<full pytest file>"}`
- Tests do `from solution import <function_name>`. Deterministic, no network, no file IO, 8 to 20 asserts.
- Prompt must demand: normal cases, edge cases (empty, single element, boundaries, negatives, duplicates, unicode where relevant, invalid input if the goal implies it), and at least one test per listed assumption.

**Builder**
- Input: goal, signature, the locked test file (read-only spec), and on retry the failing test names plus error output trimmed to 2000 chars. On re-plan: a note saying the previous approach failed on X, rewrite from scratch with a different approach.
- Output: `{"code": "<solution.py>", "notes": "..."}`. Fall back to extracting the first python code fence.

**Mutator** (two sources, combined)
1. Deterministic AST mutants, no LLM cost: flip comparisons (`<` <-> `<=`, `==` <-> `!=`), arithmetic (`+` <-> `-`), integer constants n -> n+1, `and` <-> `or`. Up to 6.
2. LLM mutants: 3 "plausible bug" versions that still look reasonable (off-by-one, missed edge case, wrong boundary).
- Drop mutants that do not compile or are identical to the original.
- Killed = any test fails, errors, or times out. `kill_rate = killed / total`.
- Run mutants in parallel (ThreadPoolExecutor).

**Verifier**
- Input: goal, assumptions, tests, code, test results, mutation summary including surviving mutants.
- Output: `{"verdict": "approve"|"reject", "confidence": 0-100, "issues": [..], "disputed_tests": [{"test_name", "reason"}]}`
- Prompt: be skeptical. Check whether the spec agent's assumptions go beyond or contradict the goal. Flag code hardcoded to the tests. Flag tests whose expected values look wrong.

### Decision step (deterministic)

- Tests fail and retries left -> RETRY with failure output.
- Same failure signature (same set of failing test names) twice in a row -> REPLAN (max 1).
- Verifier disputes a test with a reason -> spec agent gets ONE chance to fix that test, logged in the receipt as a test change, then rerun.
- Tests pass AND kill_rate >= MUT_THRESHOLD AND verifier approves -> DONE.
- Tests pass but verifier rejects -> RETRY with verifier issues (counts toward retries).
- Retries exhausted, or MAX_LLM_CALLS_PER_TASK hit -> ASK_HUMAN: generate ONE specific question about the single most blocking assumption. Status is not done.
- Also enforce a wall-clock cap per task (e.g. 120 s).

### Receipt

Save `runs/receipts/<id>.json` and print a `rich` panel:
goal, status, assumptions, tests_sha256 plus history of test changes with reasons, test results summary,
mutation `{total, killed, survivors: [short descriptions]}`, verifier `{model, verdict, confidence, issues}`,
timeline `[{step, agent, model, duration_s, tokens}]`, total tokens and LLM calls, human_question if any.

## Sandbox

`pod/sandbox.py`: `run_tests(solution_code, test_code, timeout=10) -> {passed, failed, errors, failing_tests: [{name, message}], timed_out}`

- **LocalSandbox (build first, default):** temp dir, write `solution.py` and `test_solution.py`, run
  `python -m pytest -q -p no:cacheprovider --junitxml=report.xml` with subprocess timeout.
  Strip the environment: no API keys, only PATH, a temp HOME, and PYTHONPATH set to the temp dir. Parse the junit XML. Kill on timeout.
- **OpenShellSandbox (stretch, separate prize, timebox 45 min after M3):** NVIDIA NemoClaw/OpenShell
  (https://www.nvidia.com/en-us/ai/nemoclaw). Same interface, selected by `SANDBOX=openshell`.
  If it does not work in time, keep local and say so honestly in the README.

## Evaluation (this produces the number that wins)

- Dataset: HumanEval+ via `pip install evalplus`, `from evalplus.data import get_human_eval_plus`.
  Inspect the actual field names first (expected: prompt, entry_point, canonical_solution, base_input, plus_input, atol).
  Fallback: MBPP+ from the same package.
- Goal given to agents = the problem `prompt` only (signature + docstring). Agents NEVER see canonical_solution or inputs.
- Hidden ground truth `eval/hidden.py` (never imported from `pod/`): differential testing. Run candidate and
  canonical_solution on base_input + plus_input in a subprocess with timeout, deep-copy inputs before each call,
  compare outputs (use atol for floats; exception counts as mismatch unless canonical also raises). Pass = all match.
  Cache canonical outputs.
- Sample: `EVAL_N=30` tasks, `EVAL_SEED=17`, random. Do a 10-task smoke run of condition A first. If builder-alone
  passes hidden tests on more than 90%, switch to a weaker builder model or MBPP+. Report the choice honestly.

### Conditions

| Id | Name | What runs |
|---|---|---|
| A | `solo` | Builder writes code once and says whether it is done (`{"code", "done": true/false}`). |
| B | `self_check` | Builder writes its own tests, runs them in the sandbox, same model reviews; up to MAX_RETRIES; then claims done or not. |
| C | `proof_of_done` | Full pipeline. |
| D | `pod_same_family` (optional, config only) | Full pipeline but verifier = builder model. Isolates the cross-family effect. |

### Metrics per condition

- `done_claims`, `false_done` = claimed done AND fails hidden tests, `false_done_rate = false_done / done_claims`
- `hidden_pass_rate = hidden passes / N` (did real quality go up)
- `ask_human_rate` (always show this: a system that never says done would get 0 false done)
- Avg LLM calls, tokens, wall time per task
- Condition C only: mutation kill rate before vs after test strengthening

### Harness

- `eval/run_eval.py`: asyncio with a semaphore (`CONCURRENCY`), one JSONL row per (condition, task) in
  `runs/eval/<condition>.jsonl`, resumable (skip finished rows), LLM response cache keyed by request hash in
  `runs/cache/` so reruns do not burn credits.
- Run order: 3-task smoke per condition, print cost per task, then the full run.
- `eval/report.py`: prints the table, writes `runs/eval/results.md` and `runs/eval/chart.png`
  (grouped bars: false_done_rate and hidden_pass_rate per condition, ask_human_rate annotated).

## Demo (3-minute live demo + 1-minute video)

- `python demo.py "<one-line goal>"`: live `rich` timeline of each step, e.g.
  Spec wrote 12 tests (assumptions listed) -> Builder attempt 1 -> tests 12/12 pass -> Mutation 4/6 killed, 2 survived
  -> Spec added 3 tests -> 6/6 killed -> Builder fixed a bug the new tests caught -> Verifier (Nemotron) approve 86 -> DONE -> receipt panel.
- `python demo.py --compare "<goal>"`: solo vs proof_of_done side by side. Solo says "done", Proof of Done catches the bug.
- During M4, try 5 to 10 candidate goals and keep the 2 that most reliably show a catch (one main, one backup).
  Candidates: duration parser (`"1h30m"`, `"45s"` to seconds; empty, uppercase, invalid), merge overlapping intervals
  (touching intervals, unsorted input), semantic version compare (`1.10` vs `1.9`, prerelease tags),
  roman numerals to int (subtractive forms, invalid), word wrap to width (words longer than width).
- Save a terminal recording of a good run as a fallback in case the venue Wi-Fi or API is slow.

## Repo layout

```
proof-of-done/
  CLAUDE.md  README.md  NOTES.md  requirements.txt  .env.example  .gitignore
  pod/
    config.py      # env vars, role -> (base_url, key, model)
    llm.py         # OpenAI SDK client per role, retries with backoff on 429/5xx, JSON extraction, token logging
    agents/spec.py  agents/builder.py  agents/mutator.py  agents/verifier.py
    mutation.py    # AST mutants
    sandbox.py     # LocalSandbox, OpenShellSandbox
    pipeline.py    # loop + decision step
    receipt.py
  eval/
    tasks.py  hidden.py  run_eval.py  report.py
  demo.py
  runs/            # receipts and eval results are committed as evidence; cache and logs are gitignored
```

## Engineering rules

- Python 3.11+. Deps: `openai`, `python-dotenv`, `rich`, `pytest`, `evalplus`, `matplotlib`. Nothing else unless needed.
- Temperatures: spec 0.2, builder 0.2, mutator 0.7, verifier 0.
- Log every LLM call to `runs/logs/*.jsonl` (role, model, prompt hash, tokens, latency).
- Commit after each milestone with a clear message. The user will create the public GitHub repo; ask for the remote when M1 is done.
- Batch questions to the user. Do not stop for things you can decide with a sensible default.

## Stretch (only after M4 is fully done)

1. OpenShell sandbox (separate NVIDIA prize).
2. Rule learning: each surviving-mutant pattern becomes a one-line rule appended to the spec prompt; keep a rule only if it raises kill rate on held-out tasks. Show a before/after chart.
3. Verifier calibration: plot verifier confidence vs actual hidden pass.

## README must include

Pitch, "Built today at the Recursive Agents Hackathon" with every component listed, architecture diagram,
results table and chart, how to run, sponsor usage (Crusoe for spec/builder/mutator, Nemotron as verifier,
OpenShell if done), and honest limitations (equivalent mutants, spec agent can encode a wrong assumption, small N).
