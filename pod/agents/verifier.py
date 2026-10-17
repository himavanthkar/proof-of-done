"""Verifier: a different model family (Nemotron) audits goal, assumptions, tests, code and evidence."""
from __future__ import annotations

from ..config import Role
from ..llm import Tracker
from . import ask_json

SYSTEM = """You are the independent Verifier of "Proof of Done". A spec agent wrote locked tests, a builder wrote code,
a sandbox ran the tests, and mutation testing measured how strong the tests are. You decide if "done" is earned.
Be skeptical. You are rewarded for catching false "done" claims, not for approving.

Check:
1. Do the spec agent's assumptions go beyond or contradict the goal?
2. Does the code implement the GOAL for all valid inputs, or is it hardcoded / special-cased to the tests?
3. Are any tests' expected values wrong according to the goal? (If so, list them in disputed_tests with the reason
   and the value you believe is correct.)
4. Do the surviving mutants reveal a behaviour the tests fail to pin down that matters for the goal?
5. Trace at least two goal examples through the code by hand.

Approve only if you would bet that the code is correct on hidden tests. Do not dispute a test unless you are sure.

Reply with ONLY a JSON object:
{"verdict": "approve" or "reject", "confidence": <0-100>, "issues": ["..."],
 "disputed_tests": [{"test_name": "...", "reason": "..."}]}"""


def verify(role: Role, goal: str, assumptions: list[str], tests: str, code: str, test_summary: str,
           mutation: dict | None, *, tracker: Tracker | None = None, use_cache: bool = False) -> dict:
    a = "\n".join(f"- {x}" for x in assumptions) or "- (none listed)"
    if mutation:
        m = f"{mutation['killed']}/{mutation['total']} mutants killed (kill rate {mutation['kill_rate']:.0%})."
        surv = mutation.get("survivors") or []
        if surv:
            m += "\nSurviving mutants (tests did NOT catch these):\n" + "\n".join(
                f"- {s['description']}\n{s.get('diff', '')}" for s in surv[:6])
    else:
        m = "(mutation testing not run)"
    user = (f"GOAL:\n{goal.strip()}\n\nSPEC ASSUMPTIONS:\n{a}\n\nLOCKED TESTS:\n```python\n{tests}\n```\n\n"
            f"CODE (solution.py):\n```python\n{code}\n```\n\nSANDBOX TEST RESULTS:\n{test_summary}\n\n"
            f"MUTATION TESTING:\n{m}\n")
    data, raw = ask_json(role, SYSTEM, user, tracker=tracker, step="verifier", max_tokens=3000, use_cache=use_cache)
    verdict = str(data.get("verdict", "reject")).lower().strip()
    try:
        conf = int(float(data.get("confidence", 0)))
    except (TypeError, ValueError):
        conf = 0
    disputes = [d for d in (data.get("disputed_tests") or []) if isinstance(d, dict) and d.get("test_name") and d.get("reason")]
    issues = [str(i) for i in (data.get("issues") or [])]
    if not data:
        issues = [f"verifier returned unparseable output: {raw[:200]}"]
    return {"model": role.model, "verdict": "approve" if verdict == "approve" else "reject",
            "confidence": max(0, min(100, conf)), "issues": issues, "disputed_tests": disputes}
