"""Eval harness: one JSONL row per (condition, task); resumable; LLM responses cached in runs/cache/.

  python -m eval.run_eval --conditions solo --n 10            smoke condition A
  python -m eval.run_eval --conditions all --n 3              3-task smoke per condition
  python -m eval.run_eval --conditions all                    full run (EVAL_N tasks)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import traceback

from rich.console import Console

from pod.baselines import run_self_check, run_solo
from pod.config import CONCURRENCY, EVAL_N, EVAL_SEED, RUNS, load_settings
from pod.pipeline import run_pipeline

from .hidden import hidden_pass
from .tasks import sample_tasks

console = Console()
OUT = RUNS / "eval"
CONDITIONS = {"A": "solo", "B": "self_check", "C": "proof_of_done", "D": "pod_same_family"}


def run_one(condition: str, task: dict, settings, out=OUT) -> dict:
    tid = f"{condition}-{task['id'].replace('/', '_')}"
    t0 = time.time()
    if condition == "solo":
        r = run_solo(task["goal"], task["signature"], settings=settings, task_id=tid)
    elif condition == "self_check":
        r = run_self_check(task["goal"], task["signature"], settings=settings, task_id=tid)
    else:
        st = settings.same_family_verifier() if condition == "pod_same_family" else settings
        r = run_pipeline(task["goal"], task["signature"], settings=st, task_id=tid, condition=condition, save=False)
    h = hidden_pass(task["id"], r.get("code", ""), task.get("dataset", "humaneval"))
    rdir = out / "receipts" / condition
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"{tid}.json").write_text(json.dumps(r | {"hidden": h}, indent=2, default=str))
    m = r.get("mutation") or {}
    v = r.get("verifier") or {}
    return {
        "condition": condition, "task_id": task["id"], "status": r.get("status"),
        "done_claimed": bool(r.get("done_claimed")), "hidden_pass": bool(h.get("pass")),
        "false_done": bool(r.get("done_claimed")) and not h.get("pass"),
        "ask_human": r.get("status") == "ASK_HUMAN", "human_question": r.get("human_question"),
        "llm_calls": r.get("llm_calls", 0), "tokens": r.get("total_tokens", 0), "wall_s": round(time.time() - t0, 1),
        "attempts": r.get("attempts"), "test_versions": len(r.get("test_history", [])),
        "kill_rate_before": m.get("kill_rate_before"), "kill_rate": m.get("kill_rate"),
        "mutants": m.get("total"), "verifier_verdict": v.get("verdict"), "verifier_confidence": v.get("confidence"),
        "verifier_model": v.get("model"), "decisions": [d["decision"] for d in r.get("decisions", [])],
        "hidden_detail": {k: h[k] for k in h if k != "pass"}, "error": r.get("error"),
    }


def done_ids(condition: str, out=OUT) -> set:
    f = out / f"{condition}.jsonl"
    if not f.exists():
        return set()
    return {json.loads(l)["task_id"] for l in f.read_text().splitlines() if l.strip()}


async def run_condition(condition: str, tasks: list[dict], settings, sem: asyncio.Semaphore, out=OUT) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    have = done_ids(condition, out)
    todo = [t for t in tasks if t["id"] not in have]
    console.print(f"[bold]{condition}[/bold]: {len(todo)} to run ({len(have)} already done)")
    rows, lock = [], asyncio.Lock()

    async def one(t):
        async with sem:
            try:
                row = await asyncio.to_thread(run_one, condition, t, settings, out)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]{condition} {t['id']} crashed: {e}[/red]")
                traceback.print_exc()
                return
            async with lock:
                with open(out / f"{condition}.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
                rows.append(row)
            mark = "[green]✓[/green]" if row["hidden_pass"] else "[red]✗[/red]"
            claim = "DONE" if row["done_claimed"] else row["status"]
            fd = " [bold red]FALSE DONE[/bold red]" if row["false_done"] else ""
            console.print(f"  {condition:16s} {t['id']:14s} claim={claim:10s} hidden={mark}{fd} "
                          f"calls={row['llm_calls']} tok={row['tokens']:,} {row['wall_s']}s")

    await asyncio.gather(*(one(t) for t in todo))
    if rows:
        n = len(rows)
        console.print(f"[dim]{condition}: avg {sum(r['llm_calls'] for r in rows) / n:.1f} calls, "
                      f"{sum(r['tokens'] for r in rows) / n:,.0f} tokens, {sum(r['wall_s'] for r in rows) / n:.1f}s per task[/dim]")
    return rows


async def main_async(conditions: list[str], n: int, seed: int, dataset: str, offset: int) -> None:
    settings = load_settings(use_cache=True)
    tasks = sample_tasks(n + offset, seed, dataset)[offset:]
    sem = asyncio.Semaphore(CONCURRENCY)
    console.print(f"{len(tasks)} {dataset} tasks (seed {seed}), concurrency {CONCURRENCY}, conditions {conditions}")
    await asyncio.gather(*(run_condition(c, tasks, settings, sem, OUT / dataset) for c in conditions))


def regrade(dataset: str, subdir: str | None = None) -> None:
    """Re-score every row from its saved receipt code with the current hidden grader (no LLM calls)."""
    d = OUT / (subdir or dataset)
    for f in sorted(d.glob("*.jsonl")):
        cond = f.stem
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        changed = 0
        for r in rows:
            rp = d / "receipts" / cond / f"{cond}-{r['task_id'].replace('/', '_')}.json"
            rec = json.loads(rp.read_text())
            h = hidden_pass(r["task_id"], rec.get("code", ""), dataset)
            if bool(h.get("pass")) != r["hidden_pass"]:
                changed += 1
            r["hidden_pass"] = bool(h.get("pass"))
            r["false_done"] = r["done_claimed"] and not r["hidden_pass"]
            r["hidden_detail"] = {k: h[k] for k in h if k != "pass"}
            rp.write_text(json.dumps(rec | {"hidden": h}, indent=2, default=str))
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        console.print(f"regraded {cond}: {len(rows)} rows, {changed} verdicts changed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regrade", action="store_true", help="re-score saved code with the current hidden grader")
    ap.add_argument("--dir", default=None, help="results subdir under runs/eval (default: dataset name)")
    ap.add_argument("--conditions", default="all", help="comma list of A,B,C,D or names, or 'all'")
    ap.add_argument("--n", type=int, default=EVAL_N)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--seed", type=int, default=EVAL_SEED)
    ap.add_argument("--dataset", default="humaneval", choices=["humaneval", "mbpp"])
    a = ap.parse_args()
    if a.regrade:
        regrade(a.dataset, a.dir)
        return
    if a.conditions == "all":
        conds = list(CONDITIONS.values())
    else:
        conds = [CONDITIONS.get(c.strip(), c.strip()) for c in a.conditions.split(",")]
    asyncio.run(main_async(conds, a.n, a.seed, a.dataset, a.offset))


if __name__ == "__main__":
    main()
