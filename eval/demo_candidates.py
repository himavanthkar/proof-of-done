"""Pick demo goals: which one-line goals most reliably show solo claiming done while Proof of Done catches it.

  python -m eval.demo_candidates
For each goal: one Proof of Done run (its final locked tests are the evidence), then K solo runs graded against
those tests. Writes runs/eval/demo_candidates.json.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys

from rich.console import Console
from rich.table import Table

from pod.baselines import run_solo
from pod.config import RUNS, load_settings
from pod.pipeline import run_pipeline
from pod.sandbox import run_tests

GOALS = [
    "Parse a duration string like '1h30m' or '45s' into total seconds",
    "Merge overlapping intervals given as a list of [start, end] pairs",
    "Compare two semantic version strings like '1.10.0' and '1.9.2' (including prerelease tags like '1.0.0-alpha'); return -1, 0 or 1",
    "Convert a Roman numeral string to an integer, rejecting invalid numerals",
    "Word-wrap a string to a given width, returning a list of lines",
    "Convert a snake_case or kebab-case identifier to camelCase",
    "Return the business-day count between two ISO dates (YYYY-MM-DD), excluding weekends",
    "Parse a human file size like '1.5 KB', '20MB' or '3 GiB' into bytes",
]
K = 4


def evaluate(goal: str, settings) -> dict:
    rec = run_pipeline(goal, None, settings=settings, save=True)
    fails = []
    for _ in range(K):
        s = run_solo(goal, f"def {rec.get('function_name', 'solve')}(...)", settings=settings)
        r = run_tests(s["code"], rec["tests"]) if rec.get("tests") else None
        fails.append({"claimed": s["done_claimed"], "failed": (r["failed"] + r["errors"]) if r else None,
                      "failing": [f["name"] for f in r["failing_tests"]][:4] if r else []})
    return {"goal": goal, "pod_status": rec["status"], "pod_id": rec["id"], "attempts": rec["attempts"],
            "test_versions": len(rec["test_history"]), "mutation": rec.get("mutation", {}) and
            {k: rec["mutation"][k] for k in ("killed", "total", "kill_rate_before", "kill_rate")},
            "solo_false_done": sum(1 for f in fails if f["claimed"] and f["failed"]), "solo_runs": fails,
            "wall_s": rec["wall_s"]}


def main() -> None:
    settings = load_settings(use_cache=False)
    goals = GOALS if len(sys.argv) < 2 else [g for g in GOALS if any(k in g for k in sys.argv[1:])]
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda g: evaluate(g, settings), goals))
    t = Table(title="Demo candidates")
    for c in ("goal", "PoD", "attempts", "tests v", "mutation", f"solo false done /{K}", "solo failing tests"):
        t.add_column(c)
    for r in res:
        m = r["mutation"] or {}
        t.add_row(r["goal"][:50], r["pod_status"], str(r["attempts"]), str(r["test_versions"]),
                  f"{m.get('killed', '-')}/{m.get('total', '-')}", str(r["solo_false_done"]),
                  ", ".join(sorted({n for f in r["solo_runs"] for n in f["failing"]}))[:60])
    Console().print(t)
    (RUNS / "eval" / "demo_candidates.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
