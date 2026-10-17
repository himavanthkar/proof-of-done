# Proof of Done: project brief

Built in one day at The Recursive Agents Hackathon (Crusoe x Cerebral Valley), Shack15, San Francisco, Saturday
October 17, 2026. Track: **Done Means Done**. Public repo: https://github.com/himavanthkar/proof-of-done

## The problem (one sentence)

AI coding agents fill vague goals with their own silent assumptions and then confidently report "done", even when the
work is wrong.

## The idea

Proof of Done is a team of AI agents that is **not allowed to say "done" without evidence**. Given a one-line goal, it:

1. **Writes the contract first.** A Spec agent turns the goal into explicit assumptions plus a pytest acceptance-test
   file. The tests are **locked** with a SHA-256 hash; the builder can read them but never edit them.
2. **Builds.** A Builder agent writes the code. It runs in a sandbox with no API keys and no network.
3. **Attacks its own tests (mutation testing).** The system deliberately breaks the working code (flipped
   comparisons, off-by-one constants, plus three "plausible bug" versions written by an LLM) and checks whether the
   tests catch each broken version. If too many broken versions survive, the tests are too weak, so the Spec agent must
   add tests (one round), which are re-locked and logged.
4. **Gets a second opinion from a different model family.** A Verifier, NVIDIA Nemotron, audits the goal, the
   assumptions, the tests, the code, the test results and the surviving mutants. It can reject the code, or dispute a
   test it believes is wrong.
5. **Lets plain Python decide.** The final decision is deterministic code, not an LLM: DONE only if the tests pass
   AND the mutation kill rate is at least 80% AND the verifier approves. Otherwise it RETRIES, RE-PLANS from scratch,
   FIXES a disputed test (once), or **ASKS THE HUMAN one specific question** instead of guessing.
6. **Issues a receipt.** Every run ends with a receipt (JSON plus a terminal panel): assumptions, test hash and
   history, test results, mutation results, verifier verdict, a timeline of every agent call, and cost.

## The agent team (all on Crusoe Managed Inference)

| Role | Model | Job |
|---|---|---|
| Spec agent | DeepSeek-V4-Pro | assumptions + locked tests; strengthens tests; fixes disputed tests; writes the one human question |
| Builder | Qwen3.8-27B | writes the code against the locked tests; retries with feedback; re-plans |
| Mutator | DeepSeek-V4-Pro + deterministic AST mutations | creates broken versions of the code |
| Verifier | NVIDIA Nemotron-3-Super-120B | independent cross-family audit; adjudicates tests that fail twice |
| Decision | plain Python | DONE / RETRY / REPLAN / FIX_TEST / ASK_HUMAN |

Sandbox: either a local stripped subprocess or **NVIDIA OpenShell**, a micro-VM sandbox where code runs as an
unprivileged user with outbound network denied by default and no credentials.

## Results: does it reduce false "done"?

Benchmark: MBPP+ (from evalplus), 100 held-out tasks never used for tuning. Agents see only the one-line task
description. Hidden tests compare each final program against the reference solution on hundreds of inputs.
"False done" = the system said done but the code fails the hidden tests.

| Condition | False "done" rate | Real quality (hidden-test pass) | Declined to claim done |
|---|---|---|---|
| A. Solo agent (writes code once, says done) | **32%** | 68% | 0% |
| B. Self-check (writes own tests, reviews itself) | **27%** | 69% | 11% |
| **C. Proof of Done** | **21%** | **75%** | 19% (asks one question) |
| D. Proof of Done, verifier from the same family | 19.5% | 74% | 23% |

Headlines:
- **False "done" drops by about a third (32% → 21%), and real quality goes up (68% → 75%).** It isn't winning by
  refusing: Proof of Done still claims done on 81% of tasks.
- **Of the 32 tasks where the solo agent falsely claimed done, Proof of Done fixed 10 and declined 9** (asked the
  human). 12 of the remaining 13 are tasks that no system passes: the hidden tests encode choices the one-line
  prompt never states.
- Mutation testing measurably strengthened the tests: average kill rate 89% → 96% after the Spec agent added tests.
- Pooled over all 200 tasks: false done 30% (solo), 24% (self-check), 20% (Proof of Done).
- Cost: about 5 LLM calls and 6.6k tokens per task, about 7.6 seconds per task.

## Honest findings (negative results we report)

- **The cross-family verifier did not measurably help.** A same-family verifier (condition D) did as well. The gains
  come from locked tests, mutation testing and the deterministic decision rule.
- **The verifier's confidence is barely informative:** about 80% of its approvals are correct, whether it says 95 or
  100.
- **Regressions:** on 5 tasks the solo agent's code was right but Proof of Done's spec agent pinned a different
  assumption.
- Small N (100 held-out tasks, 95% confidence intervals overlap); one seed.
- Two disclosed iterations: a prompt fix found on the dev split, and JSON mode for the verifier. The headline uses the
  untouched held-out split.

## NVIDIA OpenShell (sponsor tooling)

With `SANDBOX=openshell`, every piece of LLM-written code (builder attempts, every mutant, the solo agent's code)
runs inside an NVIDIA OpenShell micro-VM. Verified: runs as an unprivileged user, zero API keys visible, outbound
network blocked, infinite loops killed, and tampering with the locked test file detected. Replaying all 100 held-out
tasks through OpenShell gave the same outcome on 98/100 tasks (false done 22% vs 21% on the local sandbox).

## The demo story (what the audience sees)

Command: `python demo.py --compare "Return the business-day count between two ISO dates (YYYY-MM-DD), excluding weekends"`

- **Left side: the solo agent.** One LLM call, 1.4 seconds, and it says "DONE ✅", with no evidence. Checked against
  Proof of Done's locked tests, it **passes only 7 of 18**. It silently decided to "include the start date and exclude
  the end date", which appears only in its own docstring.
- **Right side: Proof of Done, live timeline.**
  - The Spec agent lists its assumptions ("the count is inclusive of both start and end dates", "weekends are Saturday
    and Sunday") and locks the tests.
  - The Builder fails one test twice.
  - Nemotron adjudicates: the *test* is wrong. The spec agent expected 4 business days from Monday Feb 26 to Friday
    Mar 1, 2024, but it is 5 (it forgot the leap day, Feb 29).
  - The Spec agent fixes that one test; it is re-locked and logged.
  - All 18 tests pass inside the NVIDIA OpenShell sandbox. Mutation testing kills 5 of 6 broken variants; Nemotron
    judges the 6th equivalent. Nemotron approves.
  - **DONE, with evidence**, and a receipt.
- **In another run of the same goal,** Proof of Done instead refused to claim done and asked: *"should the count
  include both endpoints (Mon–Fri = 5) or exclude the start date (Tue–Fri = 4)?"* That is exactly the assumption the
  solo agent made silently.

The one-line takeaway: **"done" should be a claim with evidence attached, and when the evidence can't be produced,
the right answer is one good question, not a confident guess.**

## Everything built today

Agent team, locked-test pipeline, deterministic decision step, AST plus LLM mutation engine, local and OpenShell
sandboxes, receipts, the solo and self-check baselines, the evaluation harness (async, resumable, cached), the
hidden-test grader matching evalplus' rules, the results report and chart, verifier calibration analysis, demo CLI
with live timeline and side-by-side compare, offline unit tests. Every line of code was written on October 17, 2026.
