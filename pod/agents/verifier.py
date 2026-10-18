"""Verifier: a different model family (Nemotron) audits goal, assumptions, tests, code and evidence."""
from __future__ import annotations

import math
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

EVIDENCE RULE: an objection only counts if it is executable. Whenever you reject the code or dispute a test, give 1 to 5
counterexamples: inputs the goal allows, each with the return value the GOAL requires. Derive "expected" from the goal
text and its examples alone, never from either the code or the tests. For a disputed test, use that test's input and the
value you believe is correct. Every counterexample is run against the code in a sandbox: if the code passes all of them,
your rejection is logged as unproven and ignored. Leave counterexamples empty when you approve.
"args" is the list of positional arguments and "expected" the return value, both as JSON (write tuples and sets as
lists; they are compared structurally). If the goal requires an exception, give "raises": "<ExceptionName>" instead.

Reply with ONLY a compact JSON object (no reasoning outside it, at most 5 short issues):
{"verdict": "approve" or "reject", "confidence": <0-100>, "issues": ["..."], "fix_by": "builder" or "human",
 "disputed_tests": [{"test_name": "...", "reason": "..."}], "equivalent_mutants": [<numbers>],
 "counterexamples": [{"args": [...], "expected": ..., "why": "..."}]}"""


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
    data, raw = ask_json(role, SYSTEM, user, tracker=tracker, step="verifier", max_tokens=2000, use_cache=use_cache,
                         json_mode=True)
    parsed = bool(data)  # salvaged output may have lost its counterexamples, so it does not count as parsed
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
            "fix_by": "human" if str(data.get("fix_by", "")).lower().strip() == "human" else "builder",
            "counterexamples": parse_counterexamples(data.get("counterexamples")), "parsed": parsed}


# ------------------------------------------------------------------ counterexamples: objections as executable asserts

def _finite(x) -> bool:
    if isinstance(x, float):
        return math.isfinite(x)
    if isinstance(x, (list, tuple)):
        return all(_finite(v) for v in x)
    if isinstance(x, dict):
        return all(_finite(v) for v in x.values())
    return True


def parse_counterexamples(items, limit: int = 5) -> list[dict]:
    """Keep well-formed {"args", "expected"|"raises", "why"} items; args may be a list (positional) or dict (keywords)."""
    out = []
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict) or "args" not in c or not ("expected" in c or c.get("raises")):
            continue
        args = c["args"] if isinstance(c["args"], (list, dict)) else [c["args"]]
        cx = {"args": args}
        if c.get("raises"):
            cx["raises"] = str(c["raises"]).strip()[:60]
        else:
            cx["expected"] = c["expected"]
        if not _finite([args, cx.get("expected")]) or len(repr(cx)) > 2000 or cx in [
                {k: v for k, v in o.items() if k != "why"} for o in out]:
            continue
        out.append(cx | {"why": " ".join(str(c.get("why", "")).split())[:300]})
        if len(out) >= limit:
            break
    return out


CX_HELPERS = '''
import copy as _pod_copy
import math as _pod_math


def _pod_freeze(x):
    if isinstance(x, (list, tuple)):
        return tuple(_pod_freeze(v) for v in x)
    if isinstance(x, (set, frozenset)):
        return frozenset(_pod_freeze(v) for v in x)
    if isinstance(x, dict):
        return tuple(sorted((repr(k), _pod_freeze(v)) for k, v in x.items()))
    return x


def _pod_same(got, exp):
    """Structural equality for JSON-written expectations: list == tuple, list == set, "1" key == 1 key, float tolerance."""
    if isinstance(got, (int, float)) and isinstance(exp, (int, float)):
        return got == exp or _pod_math.isclose(got, exp, rel_tol=1e-6, abs_tol=1e-9)
    if isinstance(got, (set, frozenset)) and isinstance(exp, (list, tuple, set, frozenset)):
        return {_pod_freeze(v) for v in got} == {_pod_freeze(v) for v in exp}
    if isinstance(got, (list, tuple)) and isinstance(exp, (list, tuple)):
        return len(got) == len(exp) and all(_pod_same(g, e) for g, e in zip(got, exp))
    if isinstance(got, dict) and isinstance(exp, dict):
        if len(got) != len(exp):
            return False
        for k, v in got.items():
            key = k if k in exp else str(k)
            if key not in exp or not _pod_same(v, exp[key]):
                return False
        return True
    return got == exp


def _pod_inner_tuples(x):
    return [_pod_freeze(v) if isinstance(v, list) else v for v in x] if isinstance(x, list) else x


def _pod_call(fn, args):
    """JSON has no tuples: if the call raises TypeError/AttributeError with lists, retry with inner lists as tuples,
    then with every list as a tuple."""
    pos, kw = (args, {}) if isinstance(args, list) else ([], args)
    tries = [(pos, kw),
             ([_pod_inner_tuples(a) for a in pos], {k: _pod_inner_tuples(v) for k, v in kw.items()}),
             ([_pod_freeze(a) for a in pos], {k: _pod_freeze(v) for k, v in kw.items()})]
    first = None
    for i, (p, k) in enumerate(tries):
        if i and repr((p, k)) == repr(tries[i - 1]):
            continue
        try:
            return fn(*_pod_copy.deepcopy(p), **_pod_copy.deepcopy(k))
        except (TypeError, AttributeError) as e:
            first = first or e
    raise first


def _pod_raises(fn, args, name):
    try:
        got = _pod_call(fn, args)
    except Exception as e:  # noqa: BLE001
        names = [c.__name__ for c in type(e).__mro__]
        wanted = "".join(ch if ch.isalnum() or ch == "_" else " " for ch in name).split()
        assert not wanted or any(w in names for w in wanted), f"raised {type(e).__name__}, the goal requires {name}"
        return
    raise AssertionError(f"returned {got!r:.200}, the goal requires raising {name}")
'''


def counterexample_tests(function_name: str, cxs: list[dict], tag: str = "1", numbers: list[int] | None = None,
                         helpers: bool = True) -> str:
    """Render counterexamples as pytest functions test_verifier_cx_r<tag>_<n> (needs `from solution import fn`)."""
    out = [CX_HELPERS] if helpers else []
    for n, cx in zip(numbers or range(1, len(cxs) + 1), cxs):
        why = cx.get("why") or ""
        a = cx["args"]
        call = f"{function_name}({', '.join(map(repr, a)) if isinstance(a, list) else ', '.join(f'{k}={v!r}' for k, v in a.items())})"
        body = [f"\n\ndef test_verifier_cx_r{tag}_{n}():", f"    # verifier counterexample: {call[:300]}"]
        if why:
            body.append(f"    # why: {why}")
        if "raises" in cx:
            body.append(f"    _pod_raises({function_name}, {cx['args']!r}, {cx['raises']!r})")
        else:
            body += [f"    got = _pod_call({function_name}, {cx['args']!r})",
                     f"    exp = {cx['expected']!r}",
                     "    assert _pod_same(got, exp), f\"returned {got!r:.200}, the goal requires {exp!r:.200}\""]
        out.append("\n".join(body))
    return "\n".join(out) + "\n"


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
