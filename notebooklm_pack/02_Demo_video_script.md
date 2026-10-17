# Proof of Done: 1-minute video script + 3-minute live demo run sheet

## 1-minute video (about 150 spoken words)

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:08 | Title: "Proof of Done", subtitle "Done means done" | "AI agents fill vague goals with their own assumptions, then confidently say 'done'. We built an agent team that isn't allowed to." |
| 0:08–0:20 | Terminal: `demo.py --compare` starting; the left panel shows the solo agent "DONE ✅" in 1.4 s | "Here's a one-line goal: count business days between two dates. A solo agent answers in one second and says done." |
| 0:20–0:38 | Live timeline: assumptions listed, tests locked with a sha256, a test fails twice, Nemotron adjudicates, the spec fixes the test, mutation 5 of 6 killed, verifier approves | "Proof of Done writes explicit assumptions and locks acceptance tests first. It breaks its own code to prove the tests are strong. A Nemotron verifier from a different model family audits everything, and here it caught the spec agent's own leap-day mistake." |
| 0:38–0:48 | Side-by-side panels: solo fails several locked tests; Proof of Done DONE with a receipt | "The solo agent said done, but it fails [read the number on screen] of the locked tests, because it silently made its own assumptions about the dates. Proof of Done's DONE comes with a receipt." |
| 0:48–1:00 | Results chart: false done 32% → 21%, hidden pass 68% → 75% | "On 100 held-out benchmark tasks, false 'done' drops from 32 to 21 percent and real quality rises. When it can't prove done, it asks you one question. Built today on Crusoe, with NVIDIA Nemotron and OpenShell." |

Tip: record the real terminal (macOS: Cmd+Shift+5, select the terminal window) while running the command below, then
cut to the chart (`runs/eval/chart.png`) for the last 12 seconds.

## 3-minute live demo run sheet

```bash
cd proof-of-done
./demo_video.sh            # title card -> live solo vs Proof of Done inside OpenShell -> opens the results chart
./demo_video.sh --cached   # fallback: replays a stored run (DONE via the leap-day fix; solo fails 6 of 13) in ~3 s
```

1. **Problem, 20 s.** "Agents report success they haven't earned. This is the Done Means Done track."
2. **Run it, 90 s.** Narrate the timeline as it streams:
   - the assumptions (made explicit, each has a test)
   - the sha256 lock
   - mutation testing ("we break our own code to test the tests")
   - the Nemotron verdict
   - the decision line (plain Python, not an LLM)
3. **Side by side, 30 s.** The solo agent says DONE and fails locked tests; Proof of Done is DONE with a receipt, or
   asks one precise question.
4. **Results, 30 s.** Show `runs/eval/chart.png`: held-out N=100, false done 32% → 21%, hidden pass 68% → 75%. Be
   honest: the cross-family verifier didn't measurably help; the locked tests, mutation testing and the decision rule
   did.
5. **Sponsors, 10 s.** All agents run on Crusoe Managed Inference; Nemotron is the verifier; code runs in an NVIDIA
   OpenShell micro-VM with no network and no keys.

Runs aren't deterministic: some runs end DONE after fixing a test, others end NOT DONE with one question like *"should
the count include both endpoints (Mon–Fri = 5) or exclude the start date (Tue–Fri = 4)?"* Both make the point.

**Fallbacks if Wi-Fi or the API is slow:**
- Add `--cached` to replay the last cached run.
- Open a recording: `runs/recordings/business_days_openshell.svg` or `runs/recordings/roman_compare.svg`.
- Main backup goal: `"Convert a Roman numeral string to an integer, rejecting invalid numerals"`.

## Key numbers cheat sheet

- False "done" (held-out, N=100): solo 32.0%, self-check 27.0%, **Proof of Done 21.0%**, same-family verifier 19.5%.
- Hidden-test pass: 68% / 69% / **75%** / 74%. Proof of Done still claims done on 81% of tasks.
- Of solo's 32 false dones: PoD **fixed 10**, **declined 9** (asked the human), 13 left (12 unsolvable by any condition).
- Mutation kill rate 89% → 96% after test strengthening.
- Cost: about 5 calls and 6.6k tokens per task, 7.6 s per task.
- OpenShell replay: same outcome on 98/100 tasks.
