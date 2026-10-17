"""Proof of Done pipeline: spec -> lock -> build -> sandbox -> mutate -> strengthen -> verify -> decide -> receipt."""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass

from .agents import builder as B
from .agents import mutator as M
from .agents import spec as S
from .agents import verifier as V
from .config import Settings, load_settings
from .llm import BudgetExceeded, Tracker
from .mutation import compiles, normalized, run_mutants
from .receipt import save_receipt
from .sandbox import failure_signature, run_tests, summarize

DONE, RETRY, REPLAN, FIX_TEST, ASK_HUMAN = "DONE", "RETRY", "REPLAN", "FIX_TEST", "ASK_HUMAN"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ------------------------------------------------------------------ decision step (plain Python, no LLM)

@dataclass
class Facts:
    tests_pass: bool
    retries_used: int
    max_retries: int
    fail_sig: frozenset = frozenset()
    prev_fail_sig: frozenset | None = None
    replans_used: int = 0
    kill_rate: float = 0.0
    threshold: float = 0.8
    verdict: str | None = None
    disputes: int = 0
    dispute_fix_used: bool = False
    fix_by: str = "builder"


def decide(f: Facts) -> tuple[str, str]:
    """Returns (decision, reason). Deterministic and unit-testable."""
    if not f.tests_pass:
        if f.disputes and not f.dispute_fix_used:
            return FIX_TEST, "same tests failed twice and the verifier says those tests are wrong"
        if f.prev_fail_sig is not None and f.fail_sig == f.prev_fail_sig and f.replans_used < 1:
            return REPLAN, "same failing tests twice in a row"
        if f.retries_used >= f.max_retries:
            return ASK_HUMAN, f"tests still failing after {f.retries_used} retries"
        return RETRY, "locked tests failing"
    if f.disputes and not f.dispute_fix_used:
        return FIX_TEST, "verifier disputes a locked test"
    if f.verdict == "approve" and f.kill_rate >= f.threshold:
        return DONE, f"tests pass, kill rate {f.kill_rate:.0%} >= {f.threshold:.0%}, verifier approves"
    if f.verdict == "approve":
        return ASK_HUMAN, f"kill rate {f.kill_rate:.0%} < {f.threshold:.0%}: tests too weak to prove done"
    if f.fix_by == "human":
        return ASK_HUMAN, "verifier rejects over an ambiguity in the goal that only the human can resolve"
    if f.retries_used >= f.max_retries:
        return ASK_HUMAN, "verifier rejects and retries are exhausted"
    return RETRY, "verifier rejects"


# ------------------------------------------------------------------ pipeline

def run_pipeline(goal: str, signature: str | None = None, *, settings: Settings | None = None,
                 task_id: str | None = None, emit=None, condition: str = "proof_of_done", save: bool = True) -> dict:
    s = settings or load_settings()
    rid = task_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    tr = Tracker(task_id=rid, max_calls=s.max_llm_calls, wall_clock_s=s.wall_clock_s)
    say = emit or (lambda *a, **k: None)
    roles = s.roles
    cache = s.use_cache
    R = {"id": rid, "condition": condition, "goal": goal, "status": "RUNNING", "assumptions": [],
         "models": {k: v.model for k, v in roles.items()}, "tests_sha256": None, "test_history": [],
         "test_results": None, "mutation": None, "verifier": None, "decisions": [], "attempts": 0,
         "human_question": None, "code": "", "tests": "", "done_claimed": False}

    def lock(tests: str, reason: str):
        h = sha256(tests)
        R["tests_sha256"] = h
        R["test_history"].append({"version": len(R["test_history"]) + 1, "sha256": h, "reason": reason,
                                  "n_tests": S.count_tests(tests), "n_asserts": S.count_asserts(tests)})
        R["tests"] = tests
        return tests

    def record(decision: str, reason: str):
        R["decisions"].append({"t": round(tr.elapsed(), 1), "decision": decision, "reason": reason})
        say("decision", f"{decision}: {reason}", decision=decision)

    def sandbox(code: str, tests: str) -> dict:
        assert sha256(tests) == R["tests_sha256"], "locked tests changed outside lock()"
        res = run_tests(code, tests, timeout=10, kind=s.sandbox)
        if not res.get("tests_intact", True):
            res["failed"] += 1
            res["failing_tests"].append({"name": "<tamper>", "message": "solution modified the locked test file"})
        R["test_results"] = {k: res[k] for k in ("passed", "failed", "errors", "timed_out")} | {
            "failing": [t["name"] for t in res["failing_tests"]]}
        return res

    def ok(res: dict) -> bool:
        return res["failed"] == 0 and res["errors"] == 0 and not res["timed_out"] and res["passed"] > 0

    def fix_tests(tests: str, disputes: list[dict]) -> str:
        """Spec agent gets ONE chance to fix disputed tests; every change is re-locked and logged."""
        say("step", "Spec agent re-deriving the disputed tests from the goal")
        fx = S.fix_disputed(roles["spec"], goal, tests, disputes, tracker=tr, use_cache=cache)
        new = S.normalize_spec({"tests": fx["tests"], "function_name": R["function_name"]}, sig)["tests"]
        if new.strip() != tests.strip() and compiles(new):
            say("strengthen", f"Spec revised disputed tests: {'; '.join(map(str, fx['changed']))[:220]}")
            return lock(new, "verifier dispute: " + "; ".join(map(str, fx["changed"]))[:300])
        say("strengthen", "Spec kept the disputed tests: " + "; ".join(map(str, fx["kept"]))[:220])
        return tests

    blocker = ""
    try:
        # 1. spec -> locked tests
        say("step", f"Spec agent ({roles['spec'].model}) writing assumptions + acceptance tests")
        spec = S.write_spec(roles["spec"], goal, signature, tracker=tr, use_cache=cache)
        if not compiles(spec["tests"]):
            spec = S.write_spec(roles["spec"], goal + "\n\n(Your previous test file had a syntax error. Return valid Python.)",
                                signature, tracker=tr, use_cache=cache)
        R["assumptions"] = spec["assumptions"]
        R["function_name"] = spec["function_name"]
        sig = signature or spec["signature"]
        tests = lock(spec["tests"], "initial spec")
        say("spec", f"Spec wrote {S.count_tests(tests)} tests / {S.count_asserts(tests)} asserts, "
                    f"{len(spec['assumptions'])} assumptions. Locked sha256 {R['tests_sha256'][:12]}",
            assumptions=spec["assumptions"], tests=tests)

        code, feedback, replan = None, None, None
        prev_sig, retries, replans = None, 0, 0
        strengthened, dispute_fix_used = False, False
        llm_muts, equivalent = None, set()

        while True:
            R["attempts"] += 1
            n = R["attempts"]
            label = "re-plan" if replan else ("retry" if feedback else "first try")
            say("step", f"Builder ({roles['builder'].model}) attempt {n} ({label})")
            b = B.build(roles["builder"], goal, sig, tests, feedback=feedback, replan=replan, previous_code=code,
                        tracker=tr, step=f"builder#{n}", use_cache=cache)
            code = b["code"]
            R["code"] = code
            res = sandbox(code, tests)
            say("tests", f"Sandbox: {summarize(res)}", result=res)

            if not ok(res):
                fsig = failure_signature(res)
                disputes = []
                if (prev_sig is not None and fsig == prev_sig and not dispute_fix_used and not res["timed_out"]
                        and not any(n.startswith("<") for n in fsig) and "test_solution" not in fsig):
                    # same tests failed twice: is it the code or the contract? ask the other model family
                    say("step", f"Verifier ({roles['verifier'].model}) adjudicating: tests wrong or code wrong?")
                    adj = V.adjudicate(roles["verifier"], goal, R["assumptions"], tests, code, B.format_failures(res),
                                       tracker=tr, use_cache=cache)
                    keys = {V.test_key(n) for n in fsig}
                    disputes = [x for x in adj["wrong_tests"] if V.test_key(x["test_name"]) in keys]
                    R.setdefault("adjudications", []).append(adj)
                    say("verify", f"Verifier adjudication: {len(disputes)} of {len(fsig)} failing tests look wrong",
                        verifier={"issues": [f"{x['test_name']}: {x['reason']}" for x in disputes] or adj["code_issues"]})
                d, why = decide(Facts(False, retries, s.max_retries, fsig, prev_sig, replans,
                                      disputes=len(disputes), dispute_fix_used=dispute_fix_used))
                record(d, why)
                prev_sig = fsig
                if d == FIX_TEST:
                    dispute_fix_used = True
                    tests = fix_tests(tests, disputes)
                    res = sandbox(code, tests)
                    say("tests", f"Sandbox on revised contract: {summarize(res)}", result=res)
                    if not ok(res):
                        prev_sig = failure_signature(res)
                        if retries >= s.max_retries:
                            record(ASK_HUMAN, "tests still failing after the contract fix")
                            blocker = B.format_failures(res)
                            break
                        retries += 1
                        feedback, replan = B.format_failures(res), None
                        continue
                    d = None  # contract fixed and code passes: fall through to mutation
                if d == RETRY:
                    retries += 1
                    feedback, replan = B.format_failures(res), None
                    continue
                if d == REPLAN:
                    replans += 1
                    replan = f"the previous approach failed on {', '.join(sorted(fsig))[:300]}"
                    feedback = None
                    continue
                if d is not None:
                    blocker = B.format_failures(res)
                    break
            prev_sig = None

            # 2. mutation check
            muts = M.make_mutants(roles["mutator"], goal, code, tracker=tr, use_cache=cache, reuse_llm=llm_muts)
            if llm_muts is None:
                llm_muts = [m for m in muts if m["source"] == "llm"]
            muts = [m for m in muts if normalized(m["code"]) not in equivalent]
            mut = run_mutants(muts, tests, sandbox=s.sandbox)
            say("mutation", f"Mutation: {mut['killed']}/{mut['total']} killed, {len(mut['survivors'])} survived",
                mutation=mut)

            if mut["kill_rate"] < s.mut_threshold and not strengthened and mut["survivors"]:
                strengthened = True
                before = mut["kill_rate"]
                for sv in mut["survivors"]:
                    sv["diff"] = M.short_diff(code, sv["code"])
                say("step", "Spec agent strengthening tests against surviving mutants")
                st = S.strengthen(roles["spec"], goal, tests, code, mut["survivors"], tracker=tr, use_cache=cache)
                for i in st["equivalent"]:
                    equivalent.add(normalized(mut["survivors"][i]["code"]))
                added = st["added_tests"]
                if added and compiles(tests + "\n\n" + added):
                    tests = lock(tests + "\n\n\n" + added + "\n", f"mutation strengthening: {st['reason'] or 'kill survivors'}")
                say("strengthen", f"Spec added {S.count_tests(added) if added else 0} tests, marked "
                                  f"{len(st['equivalent'])} mutant(s) equivalent. Re-locked sha256 {R['tests_sha256'][:12]}")
                muts = [m for m in muts if normalized(m["code"]) not in equivalent]
                mut = run_mutants(muts, tests, sandbox=s.sandbox)
                mut["kill_rate_before"] = before
                mut["equivalent_excluded"] = len(st["equivalent"])
                say("mutation", f"Mutation after strengthening: {mut['killed']}/{mut['total']} killed", mutation=mut)
                res = sandbox(code, tests)
                if not ok(res):
                    say("tests", f"New tests caught a bug in the current code: {summarize(res)}", result=res)
                    d, why = decide(Facts(False, retries, s.max_retries, failure_signature(res), None, replans))
                    record(d, why)
                    R["mutation"] = _mut_summary(mut)
                    if d in (RETRY, REPLAN):
                        retries += d == RETRY
                        feedback, replan = B.format_failures(res), None
                        continue
                    blocker = B.format_failures(res)
                    break
            elif "kill_rate_before" not in mut and R.get("mutation"):
                mut["kill_rate_before"] = R["mutation"].get("kill_rate_before", R["mutation"]["kill_rate"])
            R["mutation"] = _mut_summary(mut)

            # 3. verifier (different family) + decision; a disputed test gets one fix round
            while True:
                say("step", f"Verifier ({roles['verifier'].model}) auditing")
                v = V.verify(roles["verifier"], goal, R["assumptions"], tests, code, B.format_failures(res), mut,
                             tracker=tr, use_cache=cache)
                R["verifier"] = v
                say("verify", f"Verifier: {v['verdict']} (confidence {v['confidence']})", verifier=v)
                if v["equivalent_mutants"] and mut["survivors"]:
                    # survivors the other model family judges behaviourally equivalent leave the denominator
                    eqs = [mut["survivors"][i] for i in v["equivalent_mutants"] if i < len(mut["survivors"])]
                    for e in eqs:
                        equivalent.add(normalized(e["code"]))
                    muts = [m for m in muts if normalized(m["code"]) not in equivalent]
                    raw_rate = mut["kill_rate"]
                    mut = run_mutants(muts, tests, sandbox=s.sandbox) | {
                        "kill_rate_before": R["mutation"]["kill_rate_before"],
                        "equivalent_excluded": R["mutation"].get("equivalent_excluded", 0) + len(eqs)}
                    R["mutation"] = _mut_summary(mut)
                    say("mutation", f"Verifier judged {len(eqs)} survivor(s) equivalent: kill rate {raw_rate:.0%} -> "
                                    f"{mut['kill_rate']:.0%} ({mut['killed']}/{mut['total']})", mutation=mut)
                d, why = decide(Facts(True, retries, s.max_retries, kill_rate=mut["kill_rate"],
                                      threshold=s.mut_threshold, verdict=v["verdict"],
                                      disputes=len(v["disputed_tests"]), dispute_fix_used=dispute_fix_used,
                                      fix_by=v.get("fix_by", "builder")))
                record(d, why)
                if d != FIX_TEST:
                    break
                dispute_fix_used = True
                tests = fix_tests(tests, v["disputed_tests"])
                res = sandbox(code, tests)
                if not ok(res):
                    break
                mut = run_mutants(muts, tests, sandbox=s.sandbox) | {"kill_rate_before": R["mutation"]["kill_rate_before"]}
                R["mutation"] = _mut_summary(mut)

            if d == FIX_TEST or not ok(res):  # revised tests now fail the code: back to the builder
                retries += 1
                feedback, replan = B.format_failures(res), None
                if retries > s.max_retries:
                    blocker = feedback
                    record(ASK_HUMAN, "tests failing after dispute fix and retries exhausted")
                    break
                continue
            if d == DONE:
                R["status"] = "DONE"
                R["done_claimed"] = True
                break
            if d == RETRY:
                retries += 1
                feedback = "An independent verifier rejected your code:\n" + "\n".join(f"- {i}" for i in v["issues"])
                replan = None
                continue
            blocker = why + "\n" + "\n".join(v["issues"])
            break
    except BudgetExceeded as e:
        record(ASK_HUMAN, str(e))
        blocker = str(e) + ("\n" + B.format_failures(res) if "res" in locals() and res else "")
    except Exception as e:  # noqa: BLE001  (agent/API failure: never claim done)
        record(ASK_HUMAN, f"error: {type(e).__name__}: {str(e)[:200]}")
        blocker = f"{type(e).__name__}: {e}"

    if R["status"] != "DONE":
        R["status"] = "ASK_HUMAN"
        say("step", "Asking the human one question instead of guessing")
        q = S.ask_human(roles["spec"], goal, R["assumptions"], blocker, tracker=tr, use_cache=cache)
        R["human_question"] = q["question"]
        say("ask", q["question"])

    R["timeline"] = tr.timeline
    R["llm_calls"] = tr.calls
    R["total_tokens"] = tr.tokens
    R["wall_s"] = round(tr.elapsed(), 1)
    if save:
        save_receipt(R)
    say("receipt", R["status"], receipt=R)
    return R


def _mut_summary(mut: dict) -> dict:
    return {"total": mut["total"], "killed": mut["killed"], "kill_rate": round(mut["kill_rate"], 3),
            "kill_rate_before": round(mut.get("kill_rate_before", mut["kill_rate"]), 3),
            "equivalent_excluded": mut.get("equivalent_excluded", 0),
            "survivors": [f"[{x['source']}] {x['description']}" for x in mut["survivors"]],
            "results": mut.get("results", [])}
