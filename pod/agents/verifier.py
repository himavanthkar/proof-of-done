"""Verifier: a different model family (Nemotron) audits goal, assumptions, tests, code and evidence."""
from __future__ import annotations

import re

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
   For each surviving mutant, decide if it is EQUIVALENT: it returns exactly the same result as the code for EVERY
   input the goal allows, so no test could ever kill it. List only those numbers in equivalent_mutants.
   A mutant that is wrong on some valid input is NOT equivalent, even if the input is unusual.
5. Trace at least two goal examples through the code by hand.

Approve only if you would bet that the code is correct on hidden tests. Do not dispute a test unless you are sure.
If you reject, say who can fix it: "builder" if the code must change to meet the goal, or "human" if the problem is an
ambiguity in the goal itself that no code change can resolve (only the human knows the intended behaviour).

Reply with ONLY a compact JSON object (no reasoning outside it, at most 5 short issues):
{"verdict": "approve" or "reject", "confidence": <0-100>, "issues": ["..."], "fix_by": "builder" or "human",
 "disputed_tests": [{"test_name": "...", "reason": "..."}], "equivalent_mutants": [<numbers>]}"""


def verify(role: Role, goal: str, assumptions: list[str], tests: str, code: str, test_summary: str,
           mutation: dict | None, *, tracker: Tracker | None = None, use_cache: bool = False) -> dict:
    a = "\n".join(f"- {x}" for x in assumptions) or "- (none listed)"
    if mutation:
        m = f"{mutation['killed']}/{mutation['total']} mutants killed (kill rate {mutation['kill_rate']:.0%})."
        surv = mutation.get("survivors") or []
        if surv:
            m += "\nSurviving mutants (tests did NOT catch these):\n" + "\n".join(
                f"Mutant {i + 1}: {s['description']}\n{s.get('diff', '')}" for i, s in enumerate(surv[:6]))
    else:
        m = "(mutation testing not run)"
    user = (f"GOAL:\n{goal.strip()}\n\nSPEC ASSUMPTIONS:\n{a}\n\nLOCKED TESTS:\n```python\n{tests}\n```\n\n"
            f"CODE (solution.py):\n```python\n{code}\n```\n\nSANDBOX TEST RESULTS:\n{test_summary}\n\n"
            f"MUTATION TESTING:\n{m}\n")
    data, raw = ask_json(role, SYSTEM, user, tracker=tracker, step="verifier", max_tokens=1500, use_cache=use_cache,
                         json_mode=True)
    if not data:  # truncated / malformed JSON: salvage the fields we need
        vm = re.search(r'"verdict"\s*:\s*"(approve|reject)"', raw or "", re.I)
        cm = re.search(r'"confidence"\s*:\s*(\d+)', raw or "")
        if vm:
            data = {"verdict": vm.group(1).lower(), "confidence": int(cm.group(1)) if cm else 50,
                    "issues": re.findall(r'"issues"\s*:\s*\[\s*"([^"]{0,300})', raw or "")}
    verdict = str(data.get("verdict", "reject")).lower().strip()
    try:
        conf = int(float(data.get("confidence", 0)))
    except (TypeError, ValueError):
        conf = 0
    disputes = [d for d in (data.get("disputed_tests") or []) if isinstance(d, dict) and d.get("test_name") and d.get("reason")]
    issues = [str(i) for i in (data.get("issues") or [])]
    if not data:
        issues = [f"verifier returned unparseable output: {raw[:200]}"]
    n_surv = len((mutation or {}).get("survivors") or [])
    eq = set()
    for x in data.get("equivalent_mutants") or []:
        try:
            i = int(str(x).strip().lstrip("#").split()[0]) - 1
        except (ValueError, IndexError):
            continue
        if 0 <= i < min(n_surv, 6):
            eq.add(i)
    return {"model": role.model, "verdict": "approve" if verdict == "approve" else "reject",
            "confidence": max(0, min(100, conf)), "issues": issues, "disputed_tests": disputes,
            "equivalent_mutants": sorted(eq),
            "fix_by": "human" if str(data.get("fix_by", "")).lower().strip() == "human" else "builder"}


ADJUDICATE = """You are the independent Verifier of "Proof of Done". The builder has failed the SAME locked tests twice in a
row. Either the code is wrong or the tests' expected values are wrong. Decide, test by test, from the GOAL alone.
Work each failing test out by hand: compute what the goal says the answer must be, then compare with the test's
expected value. Only call a test wrong if you are certain its expected value contradicts the goal.

Reply with ONLY a JSON object:
{"wrong_tests": [{"test_name": "...", "reason": "<expected value per the goal, and why the test is wrong>"}],
 "code_issues": ["<what the code gets wrong, if anything>"]}"""


def adjudicate(role: Role, goal: str, assumptions: list[str], tests: str, code: str, failures: str, *,
               tracker: Tracker | None = None, use_cache: bool = False) -> dict:
    a = "\n".join(f"- {x}" for x in assumptions) or "- (none listed)"
    user = (f"GOAL:\n{goal.strip()}\n\nSPEC ASSUMPTIONS:\n{a}\n\nLOCKED TESTS:\n```python\n{tests}\n```\n\n"
            f"CODE:\n```python\n{code}\n```\n\nFAILURES (same tests failed on two attempts):\n{failures}\n")
    data, _ = ask_json(role, ADJUDICATE, user, tracker=tracker, step="verifier:adjudicate", max_tokens=1500,
                       use_cache=use_cache, json_mode=True)
    wrong = [d for d in (data.get("wrong_tests") or []) if isinstance(d, dict) and d.get("test_name") and d.get("reason")]
    return {"model": role.model, "wrong_tests": wrong, "code_issues": [str(x) for x in (data.get("code_issues") or [])]}


def test_key(name: str) -> str:
    """Normalize 'test_solution.py::test_x', 'test_x()' and 'test_x' to 'test_x'."""
    return str(name).split("::")[-1].split("(")[0].split("[")[0].strip()
