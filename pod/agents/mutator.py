"""Mutator: AST mutants (free) + LLM 'plausible bug' mutants, combined and de-duplicated."""
from __future__ import annotations

import difflib

from ..config import Role
from ..llm import Tracker
from ..mutation import ast_mutants, dedupe
from . import ask_json

SYSTEM = """You are the Mutator of "Proof of Done". You stress-test a test suite by writing BROKEN versions of a working
solution. Each mutant must look reasonable to a code reviewer but be WRONG for some valid input the goal allows:
an off-by-one, a missed edge case (empty / single element / duplicates / negatives), a wrong boundary (< vs <=),
a wrong tie-break or ordering, a case-sensitivity slip. Keep the same function name and signature.
Each mutant is a complete module. Do not add comments that reveal the bug.

Reply with ONLY a JSON object:
{"mutants": [{"description": "<short: what is wrong>", "code": "<full module>"}, ...]}   (exactly 3 mutants)"""


def llm_mutants(role: Role, goal: str, code: str, *, tracker: Tracker | None = None, use_cache: bool = False) -> list[dict]:
    user = f"GOAL:\n{goal.strip()}\n\nWORKING SOLUTION:\n```python\n{code}\n```\n"
    data, _ = ask_json(role, SYSTEM, user, tracker=tracker, step="mutator", max_tokens=6000, use_cache=use_cache)
    out = []
    for m in (data.get("mutants") or [])[:3]:
        if isinstance(m, dict) and isinstance(m.get("code"), str):
            out.append({"source": "llm", "description": str(m.get("description") or "plausible bug")[:120],
                        "code": m["code"]})
    return out


def make_mutants(role: Role, goal: str, code: str, *, tracker: Tracker | None = None, use_cache: bool = False,
                 llm: bool = True, reuse_llm: list[dict] | None = None) -> list[dict]:
    muts = ast_mutants(code, 6)
    if reuse_llm is not None:
        muts += reuse_llm
    elif llm:
        try:
            muts += llm_mutants(role, goal, code, tracker=tracker, use_cache=use_cache)
        except Exception:  # noqa: BLE001  (budget/API failure: AST mutants still give a signal)
            pass
    muts = dedupe(code, muts)
    for m in muts:
        m["diff"] = short_diff(code, m["code"])
    return muts


def short_diff(a: str, b: str, max_lines: int = 14) -> str:
    d = [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=1)][2:]
    return "\n".join(d[:max_lines])
