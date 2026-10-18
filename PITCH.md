# Pitch guide: how to explain Proof of Done

Website: https://himavanthkar.github.io/proof-of-done/ · Video: [media/proof_of_done_demo.mp4](media/proof_of_done_demo.mp4)

## The idea in one sentence

**An AI agent team that isn't allowed to say "done" until it can prove it. When it can't prove it, it asks you one
question instead of guessing.**

## Explain it like you're talking to a friend

You hire someone, they say "Done!", and you just have to trust them. AI coding agents are like that: you give them a
short request, they fill in the missing details by guessing, and they say "Done ✅". Often it's wrong, and you find out
later.

Proof of Done is the opposite. Before writing any code, it writes down its guesses, turns them into tests, and locks
them. Then it has to pass those tests, prove the tests are strong, and get a second opinion. Only then may it say
"done", and it hands you a receipt with the evidence.

**Analogy:** it's the difference between a student grading their own homework and a teacher who writes the answer key
before the student starts.

## How it works (and why each step matters)

| Step | What happens | Why it matters |
|---|---|---|
| 1. Write the contract | The spec agent writes every assumption ("count both dates", "reversed dates return 0") and tests for them | The hidden guesses become visible |
| 2. Lock it | The tests get a SHA-256 fingerprint | The builder can't cheat by changing the tests |
| 3. Build | The builder agent writes the code | Normal coding, but against a fixed target |
| 4. Run safely | Tests run in a sandbox (NVIDIA OpenShell): no internet, no passwords | AI-written code can't do damage |
| 5. Attack the tests | Mutation testing breaks the code on purpose and checks the tests catch every broken version | If tests can't tell broken code from good code, "tests pass" means nothing |
| 6. Second opinion | NVIDIA Nemotron checks everything and can say "this test is wrong" | Catches mistakes, even in the tests |
| 7. Decide | Plain code, not AI: DONE only if tests pass AND tests are strong AND the verifier approves | The AI doesn't grade itself |
| 8. Receipt | Assumptions, tests, results, verdict and cost for every run | Evidence, not just a claim |

If a check fails, it retries, starts over with a new approach, fixes a wrong test, or asks you one question. It never
says "done" just to finish.

## What to say while the demo plays

Goal on screen: *"Count business days between two dates, excluding weekends."*

| On screen | What you say |
|---|---|
| Title | "One-line goal. Simple, but it hides decisions: is the end date counted? What if the dates are backwards?" |
| Assumptions listed | "First it writes down 7 assumptions and locks 13 tests. Nothing is hidden." |
| 12/13 pass, RETRY | "The builder fails one test, tries again, and fails the same test." |
| Verifier adjudication | "Instead of retrying forever it asks Nemotron: is the code wrong or the test? Feb 26 to Mar 1, 2024 is 5 business days, not 4. The test forgot leap day. The AI caught its own teammate's mistake." |
| Fix, 13/13 | "The test is fixed, re-locked, and the change is recorded. All 13 pass." |
| Mutation 7/7 | "Then we break the code 7 ways on purpose. The tests catch all 7, so the tests are strong." |
| DONE + receipt | "Only now does it say DONE, with a receipt. 20 seconds." |
| Solo panel | "Same goal, a normal agent: 1 second, says done, but it silently decided to swap backwards dates. Nobody asked for that. Proof of Done wrote that rule down and tested it." |

## Numbers to memorize (held-out, 100 tasks)

- **False "done": 32% → 21%.** A normal agent's "done" was wrong about 1 in 3 times; ours about 1 in 5.
- **Correct code: 68% → 75%.** Real quality went up too.
- **Still says done 81% of the time.** It isn't winning by refusing.
- **Of the solo agent's 32 false dones:** fixed 10, asked the human on 9.
- **Demo run: 20 seconds.**

## Honest findings (say them confidently)

- A different-family verifier made no measurable difference; the power is the locked tests, mutation testing and the
  strict rule.
- With 100 tasks the gain is promising but not yet statistically significant; the next step is more tasks.
- It sometimes locks a different assumption than the user wanted, which is exactly why it asks questions.

Frame it as: *"We measured it honestly, including what didn't work. A tool about trustworthy 'done' should have
trustworthy results."*

## Real-world use cases

- **Payroll and loan interest:** day counts decide money (that's why the demo uses business days).
- **AI pull requests:** a receipt lets reviewers trust a "fixed" claim.
- **Finance and tax rules:** rounding, thresholds and cutoff dates hide expensive assumptions.
- **Healthcare calculators:** "which unit did you mean?" beats a confident guess.
- **Data pipelines:** locked tests prove transformed data follows the rules.
- **Unattended agents:** when nobody is watching, "done" has to mean done.

Line to use: *"Anywhere an AI's 'done' gets trusted without checking, which is more and more places."*

## Catchphrase, punchline, takeaway

- **Catchphrase (open with it):** **Done means done.** Short versions: "No receipt, no done." / "It doesn't guess. It
  asks." / "We made the AI prove it."
- **Punchline (right after the demo):** "The normal agent said 'done' in one second, and it was wrong. Ours took 20
  seconds, caught its own mistake, and came back with proof."
- **Takeaway (close with it):** "'Done' should be a claim with evidence attached. When there's no evidence, the right
  answer is one good question, not a confident guess."

## 60-second pitch

> AI agents have a trust problem: they fill vague goals with their own guesses, then confidently say "done". We built
> **Proof of Done**, an agent team that isn't allowed to say done without proof.
>
> It writes its assumptions down and locks them as tests before writing code. It breaks its own code on purpose to
> prove the tests are strong. And NVIDIA Nemotron double-checks everything. Here it even caught a leap-day mistake in
> our own tests.
>
> A plain rule, not an AI, decides: done only when every check passes. Otherwise it asks you one question.
>
> On 100 problems it had never seen, false "done" dropped from 32% to 21%, and correct code rose from 68% to 75%.
> Everything runs on Crusoe, with code sandboxed in NVIDIA OpenShell.
>
> **Done means done. No receipt, no done.**

## Judge questions and answers

| Question | Answer |
|---|---|
| Isn't it just refusing to answer? | No. It still says done 81% of the time, and correct code went up from 68% to 75%. Refusing alone can't improve quality. |
| What if the spec agent writes a wrong test? | It happens, and the system catches it: in the demo Nemotron caught the leap-day error, and the fix is logged in the receipt. |
| Why mutation testing? | Passing weak tests proves nothing. Breaking the code on purpose shows the tests can tell good code from bad. |
| Is it slower and more expensive? | Yes: about 5 model calls and 7.6 seconds per task versus 1 call. A wrong "done" in anything that matters costs far more. |
| Why Nemotron if the family didn't matter? | It was still the strongest check: it adjudicates disputed tests and caught real errors. We just measured honestly that a different family alone isn't the magic. |
| What's next? | More tasks for statistical confidence, whole repos instead of single functions, and receipts attached to real pull requests. |

## Demo-day checklist

1. `cd` into the project and make Terminal big (Cmd + a few times).
2. Live run with OpenShell: `./demo_video.sh`, which opens the results chart at the end.
3. If OpenShell isn't running: `brew services restart nvidia/openshell/openshell`, or use the local sandbox:
   `SANDBOX=local .venv/bin/python demo.py --compare "Return the business-day count between two ISO dates (YYYY-MM-DD), excluding weekends"`
4. If the Wi-Fi or API is slow: `./demo_video.sh --cached` replays a stored good run in about 3 seconds.
5. Backup: play `media/proof_of_done_demo.mp4`, or open the website and press **Replay**.

Practice the 60-second pitch out loud twice. If you get nervous, say the catchphrase and play the demo; it explains
itself.
