"""Builder: writes solution.py against the locked tests. Also the solo / self-check baselines' single agent."""
from __future__ import annotations

from ..config import Role
from ..llm import Tracker
from . import ask_json

SYSTEM = """You are the Builder of "Proof of Done". Write a complete, general `solution.py` that implements the goal.
A locked pytest file is the acceptance spec; it is read-only and you cannot change it.
- Implement the behaviour the goal describes for ALL valid inputs, not just the tested ones. Never hardcode test values.
- Standard library only. Include every import and helper the module needs. No printing, no input(), no file IO.
- Do not add input validation or raise exceptions unless the goal or the tests require it; unusual-but-valid inputs
  (bools, floats, tuples, mixed lists) should behave the way plain Python would.

Reply with ONLY a JSON object: {"code": "<full solution.py as a JSON string>", "notes": "<one sentence>"}"""


def build(role: Role, goal: str, signature: str, tests: str, *, feedback: str | None = None, replan: str | None = None,
          previous_code: str | None = None, tracker: Tracker | None = None, step: str = "builder",
          use_cache: bool = False) -> dict:
    user = f"GOAL:\n{goal.strip()}\n\nSIGNATURE:\n{signature}\n\nLOCKED TESTS (read-only):\n```python\n{tests}\n```\n"
    if replan:
        user += (f"\nRE-PLAN: {replan}\nThrow the previous approach away and rewrite from scratch using a DIFFERENT "
                 "algorithm or decomposition.\n")
    elif feedback:
        if previous_code:
            user += f"\nYOUR PREVIOUS solution.py:\n```python\n{previous_code}\n```\n"
        user += f"\nIT WAS REJECTED. Fix it. Feedback:\n{feedback[:2000]}\n"
    data, _ = ask_json(role, SYSTEM, user, tracker=tracker, step=step, max_tokens=4096, use_cache=use_cache,
                       code_key="code")
    return {"code": (data.get("code") or "").strip() + "\n", "notes": data.get("notes") or ""}


def format_failures(result: dict) -> str:
    lines = [f"Tests: {result['passed']} passed, {result['failed']} failed, {result['errors']} errors"
             + (" (TIMED OUT)" if result.get("timed_out") else "")]
    for t in result["failing_tests"]:
        lines.append(f"- {t['name']}: {t['message'][:400]}")
    return "\n".join(lines)[:2000]


SOLO = """You are a coding agent. Implement the goal as a complete Python module `solution.py` (standard library only,
include all imports and helpers). Then say whether the task is done.

Reply with ONLY a JSON object: {"code": "<full solution.py as a JSON string>", "done": true or false}"""


def solo(role: Role, goal: str, signature: str, *, tracker: Tracker | None = None, use_cache: bool = False) -> dict:
    user = f"GOAL:\n{goal.strip()}\n\nSIGNATURE:\n{signature}\n"
    data, _ = ask_json(role, SOLO, user, tracker=tracker, step="solo", max_tokens=4096, use_cache=use_cache,
                       code_key="code")
    done = data.get("done")
    return {"code": (data.get("code") or "").strip() + "\n", "done": done is True or str(done).lower() == "true"}


SELF_WRITE = """You are a coding agent that checks its own work. Implement the goal as `solution.py` (standard library
only, all imports and helpers included) AND write your own pytest file `test_solution.py` that starts with
`from solution import <function_name>` and has 8 to 20 asserts covering normal and edge cases.

Reply with ONLY a JSON object: {"code": "<solution.py>", "tests": "<test_solution.py>"}"""

SELF_REVIEW = """You are a coding agent reviewing YOUR OWN work. Here is the goal, your code, your tests and the sandbox
results. Decide whether the task is truly done.

Reply with ONLY a JSON object: {"done": true or false, "issues": ["..."]}"""


def self_write(role: Role, goal: str, signature: str, *, feedback: str | None = None, previous: dict | None = None,
               tracker: Tracker | None = None, use_cache: bool = False) -> dict:
    user = f"GOAL:\n{goal.strip()}\n\nSIGNATURE:\n{signature}\n"
    if feedback and previous:
        user += (f"\nPREVIOUS solution.py:\n```python\n{previous['code']}\n```\nPREVIOUS tests:\n```python\n"
                 f"{previous['tests']}\n```\nPROBLEMS:\n{feedback[:2000]}\nFix the code (or a test that is wrong).\n")
    data, raw = ask_json(role, SELF_WRITE, user, tracker=tracker, step="self:write", max_tokens=6000,
                         use_cache=use_cache, code_key="code")
    return {"code": (data.get("code") or "").strip() + "\n", "tests": (data.get("tests") or "").strip() + "\n"}


def self_review(role: Role, goal: str, code: str, tests: str, results: str, *, tracker: Tracker | None = None,
                use_cache: bool = False) -> dict:
    user = (f"GOAL:\n{goal.strip()}\n\nCODE:\n```python\n{code}\n```\n\nTESTS:\n```python\n{tests}\n```\n\n"
            f"SANDBOX RESULTS:\n{results}\n")
    data, _ = ask_json(role, SELF_REVIEW, user, tracker=tracker, step="self:review", max_tokens=1500,
                       use_cache=use_cache)
    done = data.get("done")
    return {"done": done is True or str(done).lower() == "true", "issues": data.get("issues") or []}
