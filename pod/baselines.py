"""Comparison conditions: A = solo (one shot, self-declared done), B = self_check (own tests + self review)."""
from __future__ import annotations

from .agents import builder as B
from .config import Settings, load_settings
from .llm import BudgetExceeded, Tracker
from .sandbox import run_tests, summarize


def _finish(r: dict, tr: Tracker) -> dict:
    r.update({"timeline": tr.timeline, "llm_calls": tr.calls, "total_tokens": tr.tokens, "wall_s": round(tr.elapsed(), 1)})
    r["status"] = "DONE" if r["done_claimed"] else "NOT_DONE"
    return r


def run_solo(goal: str, signature: str, *, settings: Settings | None = None, task_id: str = "solo") -> dict:
    s = settings or load_settings()
    tr = Tracker(task_id, s.max_llm_calls, s.wall_clock_s)
    r = {"id": task_id, "condition": "solo", "goal": goal, "code": "", "done_claimed": False}
    try:
        out = B.solo(s.roles["builder"], goal, signature, tracker=tr, use_cache=s.use_cache)
        r["code"], r["done_claimed"] = out["code"], out["done"] and bool(out["code"].strip())
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)[:300]
    return _finish(r, tr)


def run_self_check(goal: str, signature: str, *, settings: Settings | None = None, task_id: str = "self") -> dict:
    s = settings or load_settings()
    tr = Tracker(task_id, s.max_llm_calls, s.wall_clock_s)
    role = s.roles["builder"]
    r = {"id": task_id, "condition": "self_check", "goal": goal, "code": "", "done_claimed": False, "rounds": 0}
    prev, feedback = None, None
    try:
        for _ in range(s.max_retries + 1):
            r["rounds"] += 1
            out = B.self_write(role, goal, signature, feedback=feedback, previous=prev, tracker=tr, use_cache=s.use_cache)
            r["code"], r["tests"] = out["code"], out["tests"]
            res = run_tests(out["code"], out["tests"], timeout=10, kind=s.sandbox)
            r["test_results"] = summarize(res)
            passed = res["failed"] == 0 and res["errors"] == 0 and not res["timed_out"] and res["passed"] > 0
            if not passed:
                prev, feedback = out, B.format_failures(res)
                continue
            rev = B.self_review(role, goal, out["code"], out["tests"], B.format_failures(res), tracker=tr,
                                use_cache=s.use_cache)
            if rev["done"]:
                r["done_claimed"] = True
                break
            prev, feedback = out, "Self-review issues:\n" + "\n".join(f"- {i}" for i in rev["issues"])
    except (BudgetExceeded, Exception) as e:  # noqa: BLE001
        r["error"] = str(e)[:300]
    return _finish(r, tr)
