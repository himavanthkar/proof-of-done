"""Spec agent: goal -> explicit assumptions + a pytest file that becomes the LOCKED acceptance contract."""
from __future__ import annotations

import re

from ..config import Role
from ..llm import Tracker
from . import ask_json

SYSTEM = """You are the Spec agent of "Proof of Done", a team that never claims a task is done without evidence.
Your job: turn a goal into explicit assumptions and a pytest file of acceptance tests. The tests are LOCKED after you
write them: the builder cannot edit them, and the work only counts as done if they all pass.

Rules for the test file:
- Start with `from solution import <function_name>` (plus `import pytest` if you use pytest.raises).
- Deterministic. No network, no file IO, no randomness, no time.
- Between 8 and 20 assert statements in total, spread over several `def test_<what>():` functions with descriptive names.
- Cover: normal cases; edge cases (empty input, single element, boundaries, negatives, duplicates, unicode where relevant).
- Invalid input: test it ONLY if the goal explicitly says what must happen (e.g. "reject", "raise", "return None").
  Otherwise never require type checks or exceptions: inputs of compatible types (bool or float where an int is
  expected, tuple where a list is expected, mixed lists) must behave the way plain Python operations naturally behave.
- Every example given in the goal (docstring examples, `>>>` lines, "for example ...") must appear as an assert, verbatim.
- Write at least one test per assumption you list.
- Compute every expected value by hand, carefully, step by step. A wrong expected value is worse than a missing test.
- Floats: compare with `abs(a - b) < 1e-6` or pytest.approx.

Assumptions: list every decision the goal leaves open (input types, empty input, case sensitivity, ties, ordering,
invalid input behaviour, return type). Keep them consistent with the goal; never contradict it. Prefer the most
literal, permissive reading; take the return type and container type (list / tuple / set) from the goal's examples.

Reply with ONLY a JSON object, no prose:
{"function_name": "...", "signature": "def ...(...) -> ...:", "assumptions": ["...", "..."], "tests": "<the full pytest file as a JSON string>"}"""


def write_spec(role: Role, goal: str, signature: str | None, *, tracker: Tracker | None = None,
               use_cache: bool = False) -> dict:
    user = f"GOAL:\n{goal.strip()}\n"
    if signature:
        user += f"\nREQUIRED SIGNATURE (use exactly this function name):\n{signature}\n"
    data, raw = ask_json(role, SYSTEM, user, tracker=tracker, step="spec", max_tokens=6000, use_cache=use_cache,
                         code_key="tests")
    return normalize_spec(data, signature, raw)


def normalize_spec(data: dict, signature: str | None, raw: str = "") -> dict:
    tests = data.get("tests") or ""
    fn = data.get("function_name") or _fn_from(signature) or _fn_from_tests(tests) or "solve"
    if not tests.strip():
        raise ValueError(f"spec agent returned no tests: {raw[:300]}")
    if f"from solution import" not in tests:
        tests = f"from solution import {fn}\n" + tests
    if "pytest." in tests and "import pytest" not in tests:
        tests = "import pytest\n" + tests
    assumptions = data.get("assumptions") or []
    if isinstance(assumptions, str):
        assumptions = [assumptions]
    return {"function_name": fn, "signature": data.get("signature") or signature or f"def {fn}(...)",
            "assumptions": [str(a) for a in assumptions], "tests": tests.strip() + "\n"}


def _fn_from(signature: str | None) -> str | None:
    m = re.search(r"def\s+(\w+)\s*\(", signature or "")
    return m.group(1) if m else None


def _fn_from_tests(tests: str) -> str | None:
    m = re.search(r"from solution import (\w+)", tests)
    return m.group(1) if m else None


def count_asserts(tests: str) -> int:
    return len(re.findall(r"^\s*assert\b|pytest\.raises", tests, re.M))


def count_tests(tests: str) -> int:
    return len(re.findall(r"^def test_\w+", tests, re.M))


STRENGTHEN = """You are the Spec agent of "Proof of Done". Your locked test file passed, but MUTATION TESTING shows it is
too weak: the mutants below are deliberately broken versions of the solution that still pass every test.

For each surviving mutant decide:
- If the mutant really changes behaviour on some valid input described by the goal, write a NEW test that the
  correct solution passes and the mutant fails. Compute the expected value from the GOAL, not from either code version.
- If the mutant is EQUIVALENT (behaves identically to the original on every input the goal allows), list it as equivalent.
  Do not write a test for it.

Only ADD new test functions (new unique names starting with test_). Never modify or delete existing tests.

Reply with ONLY a JSON object:
{"added_tests": "<new test functions as python source, JSON string; empty string if none>",
 "equivalent": [<numbers of the equivalent mutants, e.g. 2>], "reason": "<one sentence>"}"""


def strengthen(role: Role, goal: str, tests: str, code: str, survivors: list[dict], *, tracker: Tracker | None = None,
               use_cache: bool = False) -> dict:
    blocks = "\n\n".join(f"### Mutant {i + 1}: {s['description']}\n```python\n{s.get('diff') or s['code']}\n```"
                         for i, s in enumerate(survivors[:8]))
    user = (f"GOAL:\n{goal.strip()}\n\nCURRENT LOCKED TESTS:\n```python\n{tests}\n```\n\nORIGINAL SOLUTION:\n```python\n"
            f"{code}\n```\n\nSURVIVING MUTANTS (diff vs original):\n{blocks}\n")
    data, _ = ask_json(role, STRENGTHEN, user, tracker=tracker, step="spec:strengthen", max_tokens=5000,
                       use_cache=use_cache, code_key="added_tests")
    eq = []
    for x in data.get("equivalent") or []:
        try:
            i = int(str(x).strip().lstrip("#").split()[0]) - 1
            if 0 <= i < len(survivors[:8]):
                eq.append(i)
        except (ValueError, IndexError):
            pass
    return {"added_tests": (data.get("added_tests") or "").strip(), "equivalent": eq,
            "reason": data.get("reason") or ""}


FIX_TEST = """You are the Spec agent of "Proof of Done". An independent verifier disputes one or more of your locked tests.
Re-derive the expected values from the GOAL alone. If the verifier is right, fix those tests. If you are right, keep them.
Do not weaken tests just to make code pass. Return the COMPLETE test file.

Reply with ONLY a JSON object:
{"tests": "<full revised pytest file, JSON string>", "changed": ["<test name>: <what changed and why>"], "kept": ["<test name>: <why kept>"]}"""


def fix_disputed(role: Role, goal: str, tests: str, disputes: list[dict], *, tracker: Tracker | None = None,
                 use_cache: bool = False, evidence: str = "") -> dict:
    d = "\n".join(f"- {x.get('test_name')}: {x.get('reason')}" for x in disputes)
    user = f"GOAL:\n{goal.strip()}\n\nLOCKED TESTS:\n```python\n{tests}\n```\n\nDISPUTED BY VERIFIER:\n{d}\n"
    if evidence:
        user += ("\nSANDBOX EVIDENCE (verifier counterexamples, expected value from the verifier's reading of the goal, "
                 f"that the current code fails):\n{evidence}\n")
    data, _ = ask_json(role, FIX_TEST, user, tracker=tracker, step="spec:fix-disputed", max_tokens=6000,
                       use_cache=use_cache, code_key="tests")
    return {"tests": data.get("tests") or tests, "changed": data.get("changed") or [], "kept": data.get("kept") or []}


ASK = """You are the Spec agent of "Proof of Done". The team could NOT prove this task done. Instead of guessing, it must
ask the human ONE question. Pick the single most blocking assumption (the one whose answer would most likely unblock
the work) and ask about it concretely, with a tiny example input. One sentence, no preamble.

Reply with ONLY a JSON object: {"question": "...", "assumption": "<the assumption it resolves>"}"""


def ask_human(role: Role, goal: str, assumptions: list[str], blocker: str, *, tracker: Tracker | None = None,
              use_cache: bool = False) -> dict:
    a = "\n".join(f"- {x}" for x in assumptions)
    user = f"GOAL:\n{goal.strip()}\n\nASSUMPTIONS MADE:\n{a}\n\nWHAT BLOCKED US:\n{blocker[:2500]}\n"
    try:
        data, _ = ask_json(role, ASK, user, tracker=tracker, step="spec:ask-human", max_tokens=800,
                           use_cache=use_cache, force=True)
    except Exception:  # noqa: BLE001
        data = {}
    q = data.get("question") or (f"Is this assumption right: {assumptions[0]}?" if assumptions else
                                 "What exactly should the function return for the failing cases?")
    return {"question": q, "assumption": data.get("assumption") or ""}
