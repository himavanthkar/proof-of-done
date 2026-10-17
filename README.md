# Proof of Done

**Agents fill vague goals with their own assumptions and then confidently report success.**

Proof of Done is an agent team on **Crusoe Managed Inference** that turns a one-line goal into **locked acceptance
tests**, builds the code, stress-tests those tests by **deliberately breaking the code (mutation testing)**, and has a
**verifier from a different model family (NVIDIA Nemotron)** check everything in a sandbox before it is allowed to say
"done". Every run ends with a **receipt** containing the evidence. When it cannot prove done, it does not guess: it asks
the human **one** specific question.

We measure the **false "done" rate** on benchmark tasks with hidden tests and compare it against an agent working alone
and an agent checking its own work.

> Track: **Done Means Done**. Built at The Recursive Agents Hackathon (Crusoe x Cerebral Valley), Shack15, San Francisco,
> Saturday Oct 17 2026.

## Results (held-out, N=100, v3)

MBPP+ (evalplus) tasks 101-200 of a seeded shuffle (seed 17), never used while building or tuning. Agents see only the
one-line task prompt. Hidden tests = differential testing against `canonical_solution` on base + plus inputs, with
evalplus' own comparison rules.

| condition | done claims | **false "done" rate** (95% CI) | hidden-test pass | declined to claim done | LLM calls / task | tokens / task |
|---|---|---|---|---|---|---|
| A solo | 100 | **32.0%** (24–42%) | 68% | 0% | 1.0 | 323 |
| B self-check (own tests + self review) | 89 | **27.0%** (19–37%) | 69% | 11% | 2.5 | 2,768 |
| **C Proof of Done** | 81 | **21.0%** (14–31%) | **75%** | 19% (asks the human one question) | 5.4 | 6,578 |
| D PoD with same-family verifier | 77 | 19.5% (12–30%) | 74% | 23% | 5.6 | 6,861 |

![results](runs/eval/chart.png)

- **False "done" drops from 32% to 21%, and real quality goes up** (hidden pass 68% → 75%). Proof of Done is not
  winning by refusing to answer: it claims done on 81% of tasks, and 64% of all tasks end in a *correct* done claim.
- **Of the 32 tasks where the solo agent falsely claimed done, Proof of Done fixed 10** (done and passes hidden tests)
  **and declined 9** (asked the human). 12 of the remaining 13 are tasks that *no* condition passes: the hidden tests
  encode choices the one-line prompt never states.
- **Mutation testing works as a test-strength gauge:** mean kill rate 89% → 96% after the spec agent strengthened the
  tests (needed on 32/100 tasks).
- **Cross-family verification: no measurable effect at this N.** Swapping Nemotron for the builder's own model (D)
  performed the same within noise. The gains come from locked tests, mutation testing and the deterministic decision
  rule, not from the verifier's family. We report this as a negative result.
- **Regressions exist:** on 5 held-out tasks the solo code passes hidden tests but Proof of Done's final code does
  not. In each one the spec agent pinned an assumption the hidden tests disagree with (regex full-match vs search,
  ignoring an `n` argument, `[]` vs `[[]]`), and the builder followed the locked contract.
- **Pooled over all 200 tasks** (dev split included, so tuning-contaminated): false done 30.0% solo, 23.8%
  self-check, **19.9% Proof of Done** (95% CI 14–27%), hidden pass 70% / 72% / 73%.
- **The verifier's confidence is barely informative.** 80% of Nemotron's approvals pass hidden tests; approvals at
  confidence 100 pass 82% vs 76% at 95–99 ([calibration](runs/eval/calibration.md)). The gate is useful because it
  is *combined* with locked tests and mutation evidence, not because the verifier is well calibrated alone.
- Cost: about 6.6k tokens and 5.4 calls per task (about 20x solo), 7.6 s wall time per task at concurrency 10.

All tables (v3 held-out, pooled, dev; archived v2 and v1): [runs/eval/results.md](runs/eval/results.md). Per-task
receipts: `runs/eval/mbpp/receipts/`.

## Demo

```bash
.venv/bin/python demo.py --compare "Convert a Roman numeral string to an integer, rejecting invalid numerals"
```

A live `rich` timeline: the spec agent writes 12 locked tests and lists its assumptions. The builder fails two of them
twice. Nemotron adjudicates ("the code is wrong, not the tests": it still accepts `IIV` and `VX`), the builder
re-plans from scratch, and all tests pass. Mutation testing shows the tests catch 7 of 8 broken variants; Nemotron
judges the 8th equivalent. DONE, with a receipt. Side by side, the solo agent says **"DONE ✅"** in 4 seconds, but
its code fails 4 of Proof of Done's 12 locked tests (`test_combined_numerals`, `test_invalid_non_roman_characters`,
`test_invalid_order`, `test_invalid_double_subtractive`).

Runs are not deterministic. On another run the tests passed 21/21, but Nemotron rejected three times because nothing
pinned down `'VIV'` (a real gap). Proof of Done refused to claim done and asked: *"Should 'VIV' (and similarly 'LXL',
'DCD') be rejected as invalid because V, L, and D cannot appear more than once?"* Both outcomes beat a confident false
"done". `--cached` replays the last cached run exactly.

Backup goal: `"Return the business-day count between two ISO dates (YYYY-MM-DD), excluding weekends"`. Here the
*verifier* catches the *spec agent's* arithmetic error (it expected 4 business days for Mon–Fri), the spec fixes that
one test (re-locked, logged), and the run ends DONE. The solo agent silently assumes an exclusive end date and passes
7/16.

We chose these goals with `eval/demo_candidates.py` (8 candidates, 1 PoD run + 4 solo runs each; results in
`runs/eval/demo_candidates.json`). Recorded runs (`runs/recordings/*.svg` + `.txt`); in every one the solo agent
claimed DONE:

| recording | Proof of Done path | solo vs PoD's locked tests |
|---|---|---|
| `roman_compare` (v2) | RETRY → adjudicate (code wrong) → REPLAN → DONE | 8/12 |
| `roman_compare_final` (v3) | RETRY → ASK_HUMAN: *"Should 'IIII', 'VV', 'IC', … and '' all raise ValueError, with 'MMMM' rejected above 3999?"* | 18/21 |
| `business_days_compare` (v2) | RETRY → verifier: test wrong → FIX_TEST (re-locked) → DONE | 7/16 |
| `business_days_final` (v3) | RETRY ×2 → ASK_HUMAN: *"should the count include both endpoints (Mon–Fri = 5) or exclude the start date (Tue–Fri = 4)?"* | 11/13 |

The last one is the pitch in one line: the solo agent silently picked one answer to that question and said "done".

## Built today at the Recursive Agents Hackathon

Every line of code in this repo was written on Oct 17 2026 during the event (see the commit history). Components:

| Component | File | What it does |
|---|---|---|
| Config | `pod/config.py` | env-driven role -> (base URL, key, model, temperature); condition D swaps the verifier |
| LLM client | `pod/llm.py` | OpenAI SDK per role, jittered backoff on 429/5xx, JSON extraction that tolerates fences/bad escapes, request-hash cache, per-call JSONL log, per-task call + wall-clock budget |
| Spec agent | `pod/agents/spec.py` | goal -> explicit assumptions + pytest file (locked by sha256); strengthens tests against surviving mutants; fixes disputed tests (once); writes the one human question |
| Builder | `pod/agents/builder.py` | writes `solution.py` against the read-only tests; retry with failures; re-plan from scratch; also the solo and self-check baselines |
| Mutator | `pod/agents/mutator.py`, `pod/mutation.py` | deterministic AST mutants (comparisons, `+/-`, constants, `and/or`) + 3 LLM "plausible bug" mutants; dedupe; parallel kill run |
| Verifier | `pod/agents/verifier.py` | Nemotron audit of goal, assumptions, tests, code, results and survivors -> verdict, confidence, issues, disputed tests, equivalent mutants; adjudicates tests that fail twice |
| Sandbox | `pod/sandbox.py` | `LocalSandbox`: temp dir + subprocess pytest, stripped env (no API keys), timeout kill, JUnit parse, tamper check on the locked test file. `OpenShellSandbox`: same interface, one `openshell sandbox exec` per run inside an NVIDIA OpenShell micro-VM (no network, no credentials) |
| OpenShell setup | `pod/openshell_setup.py` | creates the persistent sandbox from `python:3.12-slim`, uploads pytest (the sandbox has no network), smoke-tests it |
| Pipeline | `pod/pipeline.py` | the loop + a deterministic decision step (plain Python): DONE / RETRY / REPLAN / FIX_TEST / ASK_HUMAN |
| Receipt | `pod/receipt.py` | JSON evidence bundle + rich panel |
| Baselines | `pod/baselines.py` | condition A (solo) and B (self-check) |
| Eval | `eval/tasks.py`, `eval/hidden.py`, `eval/run_eval.py`, `eval/report.py` | evalplus tasks, hidden differential tests vs canonical solutions, async resumable harness, table + chart |
| Demo | `demo.py`, `eval/demo_candidates.py` | live terminal timeline, solo-vs-PoD compare, demo goal selection |
| M0 check | `pod/check.py` | lists Crusoe models, pings every role |
| Calibration (stretch 3) | `eval/calibration.py` | verifier verdict/confidence vs hidden pass, table + chart |
| Offline tests | `tests/test_core.py` | decision step paths, sandbox (fail / timeout / no keys), mutants, JSON salvage |

## Architecture

```
 one-line goal
     │
     ▼
 ┌──────────────┐  assumptions + pytest file ──► sha256 LOCK (builder cannot edit; every change logged)
 │ Spec agent   │  DeepSeek-V4-Pro on Crusoe
 └──────┬───────┘
        ▼
 ┌──────────────┐        ┌─────────────────────────────┐
 │ Builder      │──code─►│ Sandbox: pytest, no keys,   │──fail──► RETRY with failures
 │ Qwen3.8-27B  │◄───────│ timeout, tamper check       │          same failures twice ──► Verifier adjudicates:
 └──────────────┘        └──────────────┬──────────────┘            tests wrong? spec fixes once : REPLAN
                                        │ pass
                                        ▼
                         ┌─────────────────────────────┐
                         │ Mutation: 6 AST + 3 LLM      │  kill rate < 0.8 ──► Spec sees survivors, adds tests
                         │ mutants vs the locked tests  │                      (1 round), re-lock, re-run
                         └──────────────┬──────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │ Verifier: Nemotron-3-Super   │  different family from the builder
                         │ verdict, confidence, issues, │
                         │ disputed tests, equivalents  │
                         └──────────────┬──────────────┘
                                        ▼
                Decision (plain Python, no LLM):  DONE only if tests pass AND kill rate ≥ 0.8 AND verifier approves
                                                  else RETRY / REPLAN / FIX_TEST / ASK_HUMAN (one question)
                                        ▼
                                 Receipt (JSON + rich panel)
```

Budgets per task: `MAX_RETRIES=2`, one re-plan, one test-strengthening round, one disputed-test fix,
`MAX_LLM_CALLS_PER_TASK=14`, 180 s wall clock. Hitting any budget means ASK_HUMAN, never "done".

## How to run

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env            # put your Crusoe key in CRUSOE_API_KEY (single-quote it if it contains $)
.venv/bin/python -m pytest -q tests/   # offline: decision step, sandbox, mutants, JSON parsing (no key needed)
.venv/bin/python -m pod.check   # M0: list Crusoe models, ping every role
.venv/bin/python demo.py "Parse a duration string like '1h30m' or '45s' into total seconds"
.venv/bin/python demo.py --compare "<goal>"          # solo agent vs Proof of Done
.venv/bin/python demo.py --task Mbpp/641             # benchmark task, graded by hidden tests
.venv/bin/python -m eval.run_eval --conditions all --n 100 --offset 100 --dataset mbpp   # held-out split
.venv/bin/python -m eval.report --dataset mbpp --n 100 --offset 100 --name results_heldout --label "held-out tasks 101-200"
.venv/bin/python -m eval.run_eval --regrade --dataset mbpp   # re-score saved code with the hidden grader, no LLM calls
```

The eval is resumable (finished rows are skipped) and every LLM response is cached by request hash, so a rerun costs
nothing.

`--cached` on the demo replays from the LLM response cache (`runs/cache/`, gitignored) if venue Wi-Fi is slow.

## OpenShell sandbox

`SANDBOX=openshell` runs every test execution (builder code, every mutant, the solo agent's code in `--compare`) inside
an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox instead of a local subprocess. Same
`run_tests()` interface, one `openshell sandbox exec` per run (about 0.3 s): the files go in base64-encoded, pytest
runs under `timeout -s KILL`, and the JUnit XML plus a sha256 of the locked test file come back on stdout.

Setup on Apple Silicon (OpenShell v0.1.4, VM compute driver, no Docker needed). These are the steps the official
`install.sh` performs, done by hand:

```bash
gh release download v0.1.4 --repo NVIDIA/OpenShell --pattern openshell.rb      # official formula, sha256-pinned assets
brew tap-new --no-git nvidia/openshell && cp openshell.rb "$(brew --repository nvidia/openshell)/Formula/"
brew install nvidia/openshell/openshell e2fsprogs                               # the VM driver needs mke2fs
echo 'OPENSHELL_COMPUTE_DRIVER=vm' >> ~/.config/openshell/gateway.env
brew services restart nvidia/openshell/openshell
openshell gateway add https://localhost:17670 --local --name openshell
.venv/bin/python -m pod.openshell_setup        # creates sandbox 'pod-sbx' from python:3.12-slim, uploads pytest
SANDBOX=openshell .venv/bin/python demo.py --compare "<goal>"
```

What we verified inside the sandbox (`OpenShellSandbox.run_tests`): passing and failing tests are reported per test;
an infinite loop is killed at the timeout; syntax errors surface as collection errors; the code runs as uid 1000
`sandbox` with **zero** key, token or secret variables; **outbound network is denied** (`urlopen` fails with
`Permission denied`; pytest had to be uploaded because pip cannot reach PyPI); and a solution that rewrites the locked
test file is flagged (`tests_intact=False`).

**Replay of the held-out eval through OpenShell** (condition C, tasks 101-200, `runs/eval/mbpp_openshell/`):

| sandbox | done claims | false "done" rate | hidden pass | declined | s / task |
|---|---|---|---|---|---|
| local subprocess (headline v3 run) | 81 | 21.0% | 75% | 19% | 7.6 |
| **NVIDIA OpenShell** | 81 | 22.2% | 76% | 19% | 6.9 |

The same final status on 98/100 tasks and the same hidden-test verdict on 99/100. The few differences come from fresh
LLM calls where error-message text differed between sandboxes, which missed the response cache. Recording:
`runs/recordings/business_days_openshell.svg` (RETRY → FIX_TEST → DONE inside OpenShell; the solo agent claimed done
and passes 7/18).

## Sponsor usage

- **Crusoe Managed Inference** runs the whole agent team: spec + mutator (`deepseek-ai/DeepSeek-V4-Pro`), builder
  (`Qwen/Qwen3.8-27B`, thinking off), verifier (`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B`), all through the
  OpenAI-compatible endpoint `https://api.inference.crusoecloud.com/v1`. Roles use different models, which also spreads
  Crusoe's per-model rate limits.
- **NVIDIA Nemotron** is the cross-family verifier, hosted on Crusoe. Condition D swaps it for the builder's own model
  to isolate the cross-family effect.
- **NVIDIA OpenShell** runs the untrusted, LLM-written code: `SANDBOX=openshell` executes every test run (builder code,
  every mutant, solo code in the compare view) inside an OpenShell sandbox. That is a micro-VM on the macOS VM compute
  driver, running as an unprivileged user, with OpenShell's default-deny network policy and no credentials attached.
  See [OpenShell sandbox](#openshell-sandbox).

## Honest limitations

- **Equivalent mutants.** Some mutants behave identically to the original on every valid input and can never be
  killed. The spec agent (during strengthening) and the verifier can mark survivors equivalent, which removes them from
  the kill-rate denominator. That could hide a real weak spot; every receipt records the raw and adjusted kill rate and
  how many were excluded.
- **The spec agent can encode a wrong assumption.** If it misreads the goal and the verifier agrees, the code is built
  to a wrong contract and Proof of Done says "done" wrongly. Most remaining false dones are of this kind: MBPP+ hidden
  tests encode choices the one-line prompt never states (e.g. `remove_whitespaces` keeps `\n\t`,
  `removezero_ip('0.0.0.0') == '0...'`). Every condition fails those.
- **Test fixes are a trust surface.** When the verifier disputes a test, the spec agent may rewrite it (once). That is
  logged as a new locked version in the receipt, but a wrong fix could weaken the contract.
- **Small N, one seed.** 100 held-out tasks; we report Wilson 95% intervals, and they overlap more than we'd like.
- **Iterations, all disclosed.** v1 → v2: the spec/builder prompts stopped demanding input validation the goal never
  asked for (found by reading dev-split false dones). v2 → v3: JSON mode for the verifier (Nemotron sometimes produced
  3,000-token rambles, 45 s per call) plus `fix_by` routing (a rejection caused by goal ambiguity goes straight to
  ASK_HUMAN instead of burning builder retries). The v3 change was prompted by a live demo run, not by held-out results.
  Headline numbers are v3 on the held-out split (tasks 101-200); every earlier version's tables are kept in
  `runs/eval/results*.md`, and their rows are under `runs/eval/mbpp_v1/` and `runs/eval/mbpp_v2/`.
- **Benchmark choice.** HumanEval+ smoke: the solo builder passed 9/10, so (per our plan) we switched to MBPP+, whose
  vague one-line goals match the problem we target. MBPP+ solo is also about 90% on a 10-task smoke but about 70%
  over 100 tasks.
- **Builder model.** We started with Gemma 4 31B, but it ran at about 15 tok/s on the shared endpoint, so we switched
  to Qwen3.8-27B (thinking off).
- **Cache sharing.** C and D send identical spec/builder requests, so D often hits the response cache; D's wall time is
  understated (calls and tokens are counted either way).
- **Hidden-grader fidelity.** `eval/hidden.py` re-implements evalplus' comparison rules and special oracles (set
  equality for 8 MBPP tasks, not-None tasks, float tolerance). Our first run used a stricter comparator; every row was
  regraded from its saved code (no LLM calls) once we noticed.
- **OpenShell scope.** The headline eval ran on the local subprocess sandbox (stripped env, timeouts), which is not a
  security boundary. OpenShell was added afterwards and validated by replaying held-out condition C through it (see
  below). For speed it reuses one persistent sandbox VM with a fresh temp dir per run, rather than one VM per run.
