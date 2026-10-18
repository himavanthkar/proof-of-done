"""Verifier interventions vs hidden tests: did the verifier's objections catch real bugs, or raise false alarms?

  python -m eval.interventions --dir mbpp --baseline-dir mbpp --n 100 --offset 100 --name interventions_heldout_v4
writes runs/eval/<name>.md

- block: the task ended not-done because of the verifier (final decision is a verifier rejection). Real if the final
  code fails hidden tests, false alarm if it passes.
- let through: the task was claimed done and the code fails hidden tests (= false done).
- objection (v4 receipts only): every verifier reject / dispute, with its counterexamples run in the sandbox. The code
  the verifier objected to is stored in the receipt, so each objection is graded on the hidden tests directly:
  right = that code fails hidden tests.
"""
from __future__ import annotations

import argparse
import json

from pod.config import EVAL_SEED, RUNS

from .hidden import hidden_pass
from .tasks import sample_tasks

OUT = RUNS / "eval"
CONDS = [("proof_of_done", "C (Nemotron verifier)"), ("pod_same_family", "D (Qwen verifier = builder model)")]
VERIFIER_BLOCK = ("verifier rejects", "verifier counterexamples")


def receipts(d: str, cond: str, ids: set) -> dict[str, tuple[dict, dict]]:
    f = OUT / d / f"{cond}.jsonl"
    if not f.exists():
        return {}
    rows = {}
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["task_id"] in ids:
                rows[r["task_id"]] = r
    out = {}
    for tid, row in rows.items():
        rp = OUT / d / "receipts" / cond / f"{cond}-{tid.replace('/', '_')}.json"
        out[tid] = (row, json.loads(rp.read_text()))
    return out


def gate_counts(data: dict) -> dict:
    blocks = [(tid, row["hidden_pass"]) for tid, (row, rec) in data.items() if not row["done_claimed"] and (
        rec.get("decisions") and any(k in rec["decisions"][-1]["reason"] for k in VERIFIER_BLOCK)
        # v4: the task stays not-done because the code keeps failing a locked verifier counterexample
        or any(t.startswith("test_verifier_cx_") for t in (rec.get("test_results") or {}).get("failing", [])))]
    return {"n": len(data), "blocks": len(blocks), "blocks_real": sum(not p for _, p in blocks),
            "blocks_false": sum(p for _, p in blocks), "approved_wrong": sum(r["false_done"] for r, _ in data.values()),
            "done_claims": sum(r["done_claimed"] for r, _ in data.values()),
            "hidden_pass": sum(r["hidden_pass"] for r, _ in data.values()),
            "verifier_retries": sum(d["decision"] == "RETRY" and any(k in d["reason"] for k in VERIFIER_BLOCK)
                                    for _, rec in data.values() for d in rec.get("decisions") or []),
            "block_ids": [t for t, _ in blocks]}


def objection_counts(data: dict, dataset: str) -> dict:
    rows, grades = [], {}
    for tid, (row, rec) in data.items():
        for o in rec.get("verifier_objections") or []:
            key = (tid, o["code_sha256"])
            if key not in grades:
                grades[key] = bool(hidden_pass(tid, o["code"], dataset).get("pass"))
            rows.append({"task": tid, "proven": o["proven"], "verdict": o["verdict"], "disputes": len(o["disputed_tests"]),
                         "cx": len(o["counterexamples"]), "cx_failed": len(o["failed"]),
                         "cx_invalid": sum(c.get("result") == "invalid" for c in o["counterexamples"]),
                         "right": not grades[key], "decision": o["decision"],
                         "final_done": row["done_claimed"], "final_pass": row["hidden_pass"]})

    def part(sel):
        return {"n": len(sel), "right": sum(r["right"] for r in sel), "false_alarm": sum(not r["right"] for r in sel)}

    proven = [r for r in rows if r["proven"]]
    unproven = [r for r in rows if r["proven"] is False]
    unchecked = [r for r in rows if r["proven"] is None]
    return {"objections": len(rows), "tasks": len({r["task"] for r in rows}),
            "with_cx": sum(r["cx"] > 0 for r in rows), "cx": sum(r["cx"] for r in rows),
            "cx_failed": sum(r["cx_failed"] for r in rows), "cx_invalid": sum(r["cx_invalid"] for r in rows),
            "proven": part(proven), "unproven": part(unproven), "unchecked": part(unchecked),
            "proven_then_fixed": sum(r["right"] and r["final_done"] and r["final_pass"] for r in proven),
            "proven_false_then_broken": sum(not r["right"] and not r["final_pass"] for r in proven),
            "unproven_right_then_false_done": sum(r["right"] and r["final_done"] and not r["final_pass"] for r in unproven),
            "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="mbpp_v4")
    ap.add_argument("--baseline-dir", default="mbpp")
    ap.add_argument("--dataset", default="mbpp")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--offset", type=int, default=100)
    ap.add_argument("--seed", type=int, default=EVAL_SEED)
    ap.add_argument("--name", default="interventions_heldout_v4")
    a = ap.parse_args()
    ids = {t["id"] for t in sample_tasks(a.n + a.offset, a.seed, a.dataset)[a.offset:]}

    md = [f"# Verifier interventions vs hidden tests (seeded tasks {a.offset + 1}-{a.offset + a.n}, seed {a.seed})", "",
          f"Baseline `runs/eval/{a.baseline_dir}/` (v3: rejections need no evidence) vs `runs/eval/{a.dir}/` (v4: a "
          "rejection or test dispute counts only if the code fails one of the verifier's counterexamples in the "
          "sandbox). Generated by `python -m eval.interventions`.", "",
          "| condition | run | done claims | hidden pass | verifier blocks done | real | false alarm | wrong code let through (false done) | builder retries ordered by verifier |",
          "|---|---|---|---|---|---|---|---|---|"]
    obj_md = []
    for cond, label in CONDS:
        for tag, d in (("v3", a.baseline_dir), ("v4", a.dir)):
            data = receipts(d, cond, ids)
            if not data:
                continue
            g = gate_counts(data)
            md.append(f"| {label} | {tag} | {g['done_claims']}/{g['n']} | {g['hidden_pass']} | {g['blocks']} | "
                      f"{g['blocks_real']} | {g['blocks_false']} | {g['approved_wrong']} | {g['verifier_retries']} |")
            if tag == "v4":
                o = objection_counts(data, a.dataset)
                p, u = o["proven"], o["unproven"]
                obj_md += [
                    f"### {label}", "",
                    f"- {o['objections']} objections (rejections or disputes) on {o['tasks']} tasks; {o['with_cx']} came "
                    f"with counterexamples ({o['cx']} counterexamples, {o['cx_failed']} failed on the code, "
                    f"{o['cx_invalid']} unrunnable).",
                    f"- **proven** (code fails >= 1 counterexample): {p['n']}. The objected-to code fails hidden tests "
                    f"in {p['right']} (real), passes in {p['false_alarm']} (false alarm).",
                    f"- **unproven** (logged, not acted on): {u['n']}. Real {u['right']}, false alarm {u['false_alarm']}.",
                    f"- unchecked (verifier reply unparseable, old blocking rule applied): {o['unchecked']['n']}. "
                    f"Real {o['unchecked']['right']}, false alarm {o['unchecked']['false_alarm']}.",
                    f"- proven and real, then fixed (final done + hidden pass): {o['proven_then_fixed']}; "
                    f"proven false alarm that left the task failing hidden tests: {o['proven_false_then_broken']}.",
                    f"- unproven but real, task ended as a false done (the cost of requiring evidence): "
                    f"{o['unproven_right_then_false_done']}.", "",
                    "| task | verdict | disputes | counterexamples (failed) | proven | objection right? | decision | final |",
                    "|---|---|---|---|---|---|---|---|"]
                for r in o["rows"]:
                    fin = ("done" if r["final_done"] else "not done") + (", pass" if r["final_pass"] else ", fail")
                    obj_md.append(f"| {r['task']} | {r['verdict']} | {r['disputes']} | {r['cx']} ({r['cx_failed']}) | "
                                  f"{ {True: 'yes', False: 'no', None: 'unchecked'}[r['proven']]} | "
                                  f"{'real' if r['right'] else 'false alarm'} | "
                                  f"{r['decision']} | {fin} |")
                obj_md.append("")
    text = "\n".join(md + ["", "## Every v4 objection, graded on hidden tests", ""] + obj_md) + "\n"
    (OUT / f"{a.name}.md").write_text(text)
    print(text)
    print(f"wrote {OUT / (a.name + '.md')}")


if __name__ == "__main__":
    main()
