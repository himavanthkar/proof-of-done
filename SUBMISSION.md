# Submission: Proof of Done

Every number below is copied from `runs/eval/results_heldout.md`, `runs/eval/results_all200.md`,
`runs/eval/calibration.md` and `runs/eval/results_openshell.md`.

**Project name:** Proof of Done

**Repo:** https://github.com/himavanthkar/proof-of-done

**Video (≈1 min):** https://github.com/himavanthkar/proof-of-done/blob/main/media/proof_of_done_demo.mp4

**Problem statement / track:** Done Means Done

## Description

AI agents fill vague goals with their own assumptions, then confidently report "done". Proof of Done is an agent team
on Crusoe Managed Inference that is not allowed to say "done" without evidence.

From a one-line goal:
1. A spec agent writes explicit assumptions and pytest acceptance tests, locked by SHA-256 so the builder can't edit
   them.
2. A builder writes the code in a sandbox.
3. Mutation testing deliberately breaks the code to prove the tests are strong; weak tests get strengthened and
   re-locked.
4. An NVIDIA Nemotron verifier audits the goal, assumptions, tests, code and evidence, and can dispute a test it
   believes is wrong.
5. A deterministic Python rule allows DONE only when the tests pass, at least 80% of mutants are killed, and the
   verifier approves. Otherwise it retries, re-plans, fixes a disputed test once, or asks the human one specific
   question instead of guessing.
6. Every run ends with a receipt (assumptions, test hash history, mutation results, verdict, timeline, cost).

**Results (MBPP+, 100 held-out tasks never used for tuning; hidden tests = differential testing vs the reference
solution):**

| Condition | False "done" rate (95% CI) | Hidden-test pass | Declined to claim done |
|---|---|---|---|
| Solo agent | 32.0% (24%–42%) | 68% | 0% |
| Self-check agent | 27.0% (19%–37%) | 69% | 11% |
| **Proof of Done** | **21.0% (14%–31%)** | **75%** | 19% |
| Proof of Done, same-family verifier | 19.5% (12%–30%) | 74% | 23% |

- Of the 32 tasks where the solo agent falsely claimed done, Proof of Done fixed 10 and declined 9 (asked the human);
  of the 13 it still got wrong, 12 are tasks no condition passes.
- Mutation kill rate rose from 89% before test strengthening to 96% after (strengthened on 32/100 tasks).
- Pooled over all 200 tasks: false done 30.0% solo, 23.8% self-check, 19.9% Proof of Done.
- Cost: 5.4 LLM calls and 6,578 tokens per task, 7.6 s per task (held-out).

**Honest findings:**
- **The cross-family verifier did not measurably help.** The same-family verifier scored 19.5% vs 21.0%, within
  noise. The gains come from locked tests, mutation testing and the deterministic decision rule.
- **Verifier confidence is barely informative:** 80% of approvals were right, 82% at confidence 100 vs 76% at 95–99.
- **Regressions:** on 5 tasks the solo agent's code passes hidden tests but Proof of Done's does not, because its spec
  locked a different assumption.
- **Small N:** the 95% intervals overlap.
- Prompts were tuned on the dev split (tasks 1–100); headline numbers are from tasks 101–200.

## Prize categories

**Best Use of Nemotron: yes.** `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` on Crusoe is the independent verifier:
1. It audits every candidate "done" (verdict, confidence, issues).
2. It adjudicates tests that fail twice ("is the code wrong or the test?"). In the demo it caught the spec agent's
   leap-day arithmetic error, and the test was fixed and re-locked.
3. It disputes wrong tests.
4. It marks surviving mutants that are equivalent to the original code.
5. It routes goal ambiguity to the human (`fix_by: human`).

It uses JSON mode. We report that its family made no measurable difference compared with a same-family verifier.

**Best Use of NemoClaw & OpenShell: yes, OpenShell** (NemoClaw not used).
- **What runs there:** with `SANDBOX=openshell`, all LLM-written code runs inside an NVIDIA OpenShell sandbox: every
  builder attempt, every mutant, and the solo agent's code in the compare view.
- **The sandbox:** a micro-VM on the macOS VM compute driver, OpenShell v0.1.4. Code runs as an unprivileged user with
  default-deny network and no credentials, under a kill timeout, with a tamper check on the locked tests.
- **Replay:** running held-out condition C through OpenShell gave false done 22.2%, hidden pass 76%, the same final
  status on 98/100 tasks and the same hidden-test verdict on 99/100 compared with the local sandbox.

## NVIDIA tools used

- Nemotron-3-Super-120B-A12B (via Crusoe) as the verifier.
- NVIDIA OpenShell v0.1.4 (CLI, gateway, VM compute driver) as the execution sandbox.

## Crusoe Managed Inference usage

The whole agent team runs on Crusoe's OpenAI-compatible endpoint (`https://api.inference.crusoecloud.com/v1`):

| Role | Model |
|---|---|
| Spec agent and mutator | `deepseek-ai/DeepSeek-V4-Pro` |
| Builder | `Qwen/Qwen3.8-27B`, thinking off |
| Verifier | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` |
| Same-family control | Qwen as the verifier |

- **Volume:** 1,500 graded condition-task runs across the evaluation (all versions and the OpenShell replay), at
  concurrency 8–10.
- **Reliability:** retries with backoff on 429/5xx and a request-hash response cache.

## Crusoe feedback

- **Good:** the OpenAI-compatible endpoint worked on the first call with every model; `/v1/models` exposes
  `supported_parameters` (including `logprobs` and `response_format`), which made per-model feature checks easy. We
  hit no 429s at concurrency 10.
- **Model IDs don't match the docs:** the docs list `nvidia/Nemotron-3-Super-120B-A12B`, but the live ID is
  `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B`, so the docs' ID returns 404. Copying IDs from `/v1/models` was
  essential.
- **Gemma throughput:** `google/gemma-4-31b-it` ran at about 15 tok/s on the shared endpoint, versus roughly 150–250
  tok/s for Qwen3.8-27B, gpt-oss-120b and DeepSeek-V4-Flash, so we switched builders.
- **Nemotron without JSON mode:** Nemotron-3-Super sometimes produced 3,000-token rambles (about 45 s) instead of the
  requested JSON. `response_format: json_object` fixed it.
- **No rate-limit headers:** the `x-ratelimit-*` response headers described in the docs were not returned for our
  project.
- **DeepSeek-V4-Pro latency tail:** under load, occasional calls were many times slower than the median; a
  per-request latency field or a priority tier would help agent loops.

## Partner feedback (NVIDIA OpenShell)

- **Good:** after setup, `openshell sandbox exec` round-trips took about 0.2–0.3 s; default-deny networking and the
  credential-free environment worked out of the box; the CLI `--help` was excellent.
- **Docker requirement:** on macOS without Docker Desktop running, the gateway failed with "no compute driver
  configured". Switching to `OPENSHELL_COMPUTE_DRIVER=vm` worked, but it also needed `e2fsprogs` (mke2fs) on PATH. The
  error message said so clearly; the quickstart didn't mention it.
- **Missing docs:** the docs lacked `exec` / `upload` examples, so we learned them from `--help`.
- **Upload nesting:** `sandbox upload <dir> <dest>` nests the source folder name under `dest`, which surprised us.
- **No packages inside:** with no network inside the sandbox, Python packages (pytest) must be uploaded. A documented
  offline-dependency pattern would help.
