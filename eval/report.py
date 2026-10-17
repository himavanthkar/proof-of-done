"""Results table + chart from runs/eval/<dataset>/<condition>.jsonl.

  python -m eval.report --dataset mbpp --n 100
writes runs/eval/results.md and runs/eval/chart.png
"""
from __future__ import annotations

import argparse
import json
import math

from rich.console import Console
from rich.table import Table

from pod.config import EVAL_SEED, RUNS

from .tasks import sample_tasks

OUT = RUNS / "eval"
ORDER = [("A", "solo"), ("B", "self_check"), ("C", "proof_of_done"), ("D", "pod_same_family")]
LABEL = {"solo": "A solo", "self_check": "B self-check", "proof_of_done": "C Proof of Done",
         "pod_same_family": "D PoD, same-family verifier"}
# reference categorical palette, slots 1-2 (light surface)
BLUE, ORANGE, SURFACE, INK, INK2, GRID = "#2a78d6", "#eb6834", "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load(dataset: str, ids: set) -> dict[str, list[dict]]:
    out = {}
    for _, cond in ORDER:
        f = OUT / dataset / f"{cond}.jsonl"
        if not f.exists():
            continue
        rows = {}
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r["task_id"] in ids:
                    rows[r["task_id"]] = r
        out[cond] = list(rows.values())
    return out


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    claims = sum(r["done_claimed"] for r in rows)
    fd = sum(r["false_done"] for r in rows)
    hp = sum(r["hidden_pass"] for r in rows)
    ask = sum(r.get("ask_human") or (not r["done_claimed"]) for r in rows)
    kb = [r["kill_rate_before"] for r in rows if r.get("kill_rate_before") is not None]
    ka = [r["kill_rate"] for r in rows if r.get("kill_rate") is not None]
    lo, hi = wilson(fd, claims)
    return {"n": n, "done_claims": claims, "false_done": fd, "false_done_rate": fd / claims if claims else 0.0,
            "fdr_ci": (lo, hi), "hidden_pass_rate": hp / n if n else 0.0, "hidden_pass": hp,
            "not_done_rate": ask / n if n else 0.0,
            "true_done_rate": (claims - fd) / n if n else 0.0,
            "calls": sum(r["llm_calls"] for r in rows) / n if n else 0, "tokens": sum(r["tokens"] for r in rows) / n if n else 0,
            "wall": sum(r["wall_s"] for r in rows) / n if n else 0,
            "kill_before": sum(kb) / len(kb) if kb else None, "kill_after": sum(ka) / len(ka) if ka else None,
            "strengthened": sum(1 for r in rows if (r.get("test_versions") or 1) > 1)}


def chart(ms: dict, path, dataset: str, n: int, label: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conds = [c for _, c in ORDER if c in ms]
    x = range(len(conds))
    w = 0.36
    fig, ax = plt.subplots(figsize=(9.5, 5), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    fdr = [ms[c]["false_done_rate"] * 100 for c in conds]
    hpr = [ms[c]["hidden_pass_rate"] * 100 for c in conds]
    b1 = ax.bar([i - w / 2 - 0.01 for i in x], fdr, w, color=ORANGE, label="false “done” rate (of done claims)", zorder=3)
    b2 = ax.bar([i + w / 2 + 0.01 for i in x], hpr, w, color=BLUE, label="hidden-test pass rate (of all tasks)", zorder=3)
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, f"{b.get_height():.0f}%", ha="center",
                    va="bottom", fontsize=9, color=INK)
    for i, c in enumerate(conds):
        ax.text(i, -15, f"declined to claim done: {ms[c]['not_done_rate'] * 100:.0f}%", ha="center", fontsize=7.5, color=INK2)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABEL[c] for c in conds], fontsize=9, color=INK)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of tasks", color=INK2, fontsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)
    ax.legend(frameon=False, fontsize=9, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, labelcolor=INK)
    ax.set_title(f"False “done” vs real quality, {dataset.upper()}+ hidden tests, N={n}" + (f" ({label})" if label else ""), fontsize=11, color=INK,
                 loc="left", pad=30)
    fig.subplots_adjust(bottom=0.2)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="mbpp")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=EVAL_SEED)
    ap.add_argument("--offset", type=int, default=0, help="skip the first OFFSET tasks of the seeded order")
    ap.add_argument("--dir", default=None, help="results subdir under runs/eval (default: dataset)")
    ap.add_argument("--name", default="results", help="output basename: <name>.md / <name>.png")
    ap.add_argument("--label", default="", help="split label for the title, e.g. 'held-out tasks 101-200'")
    a = ap.parse_args()
    ids = {t["id"] for t in sample_tasks(a.n + a.offset, a.seed, a.dataset)[a.offset:]}
    data = load(a.dir or a.dataset, ids)
    ms = {c: metrics(r) for c, r in data.items() if r}

    t = Table(title=f"{a.dataset.upper()}+ hidden tests, seed {a.seed} {a.label}")
    cols = ["condition", "N", "done claims", "false done", "false done rate (95% CI)", "hidden pass", "not done",
            "calls/task", "tokens/task", "s/task"]
    for c in cols:
        t.add_column(c, justify="right" if c != "condition" else "left")
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, c in ORDER:
        if c not in ms:
            continue
        m = ms[c]
        row = [LABEL[c], str(m["n"]), str(m["done_claims"]), str(m["false_done"]),
               f"{m['false_done_rate']:.1%} ({m['fdr_ci'][0]:.0%}–{m['fdr_ci'][1]:.0%})",
               f"{m['hidden_pass_rate']:.0%}", f"{m['not_done_rate']:.0%}", f"{m['calls']:.1f}",
               f"{m['tokens']:,.0f}", f"{m['wall']:.1f}"]
        t.add_row(*row)
        md.append("| " + " | ".join(row) + " |")
    Console().print(t)

    notes = []
    if "proof_of_done" in ms and ms["proof_of_done"]["kill_before"] is not None:
        m = ms["proof_of_done"]
        notes.append(f"- Proof of Done mutation kill rate: {m['kill_before']:.0%} before test strengthening, "
                     f"{m['kill_after']:.0%} after (tests strengthened on {m['strengthened']}/{m['n']} tasks).")
    for c in ("solo", "proof_of_done"):
        if c in ms:
            notes.append(f"- {LABEL[c]}: {ms[c]['true_done_rate']:.0%} of tasks ended with a *correct* done claim.")
    if "solo" in data and "proof_of_done" in data:
        pod = {r["task_id"]: r for r in data["proof_of_done"]}
        sfd = [r for r in data["solo"] if r["false_done"] and r["task_id"] in pod]
        fixed = sum(1 for r in sfd if pod[r["task_id"]]["done_claimed"] and pod[r["task_id"]]["hidden_pass"])
        declined = sum(1 for r in sfd if not pod[r["task_id"]]["done_claimed"])
        still = sum(1 for r in sfd if pod[r["task_id"]]["false_done"])
        allfail = sum(1 for r in sfd if pod[r["task_id"]]["false_done"]
                      and not any(x["task_id"] == r["task_id"] and x["hidden_pass"] for cc in data.values() for x in cc))
        notes.append(f"- Of the {len(sfd)} tasks where solo falsely claimed done, Proof of Done **fixed {fixed}** (done + "
                     f"passes hidden tests), **declined {declined}** (asked the human), and still falsely claimed {still} "
                     f"({allfail} of those no condition passes).")
        regress = sum(1 for r in data["solo"] if r["hidden_pass"] and r["task_id"] in pod and not pod[r["task_id"]]["hidden_pass"])
        notes.append(f"- Regressions: {regress} tasks where solo's code passes hidden tests but Proof of Done's final code does not.")
    text = (f"# Results{(': ' + a.label) if a.label else ''}\n\n{a.dataset.upper()}+ (evalplus), N={a.n} tasks "
            f"(seeded order {a.offset + 1}-{a.offset + a.n}), seed {a.seed}. Agents see only the task "
            "prompt; hidden tests = differential testing against `canonical_solution` on base + plus inputs.\n\n"
            "- **false done rate** = claimed done AND failed hidden tests / done claims\n"
            "- **hidden pass** = final code passes hidden tests / all tasks (regardless of claim)\n"
            "- **not done** = the system declined to claim done (Proof of Done asks the human one question)\n\n"
            + "\n".join(md) + "\n\n" + "\n".join(notes) + f"\n\n![chart]({a.name}.png)\n")
    (OUT / f"{a.name}.md").write_text(text)
    chart(ms, OUT / f"{a.name}.png", a.dataset, a.n, a.label)
    print("\n".join(notes))
    print(f"wrote {OUT / (a.name + '.md')} and {OUT / (a.name + '.png')}")


if __name__ == "__main__":
    main()
