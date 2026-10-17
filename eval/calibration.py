"""Stretch 3: verifier calibration. Does the verifier's verdict/confidence predict hidden-test pass?

  python -m eval.calibration --dir mbpp --condition proof_of_done
writes runs/eval/calibration.md and runs/eval/calibration.png
"""
from __future__ import annotations

import argparse
import json

from pod.config import RUNS

from .report import BLUE, GRID, INK, INK2, SURFACE, wilson

OUT = RUNS / "eval"
BINS = [(0, 79), (80, 89), (90, 94), (95, 99), (100, 100)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="mbpp")
    ap.add_argument("--condition", default="proof_of_done")
    a = ap.parse_args()
    rows = [json.loads(l) for l in (OUT / a.dir / f"{a.condition}.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("verifier_verdict")]

    def cell(v, h):
        return sum(1 for r in rows if r["verifier_verdict"] == v and r["hidden_pass"] == h)

    ap_pass, ap_fail, rj_pass, rj_fail = cell("approve", True), cell("approve", False), cell("reject", True), cell("reject", False)
    lines = [f"# Verifier calibration ({a.condition}, {len(rows)} tasks where the verifier ran)", "",
             "Final verifier verdict vs hidden tests (the verifier never sees hidden tests).", "",
             "| verifier verdict | hidden pass | hidden fail | precision |", "|---|---|---|---|",
             f"| approve | {ap_pass} | {ap_fail} | {ap_pass / max(1, ap_pass + ap_fail):.0%} of approvals were right |",
             f"| reject | {rj_pass} | {rj_fail} | {rj_fail / max(1, rj_pass + rj_fail):.0%} of rejections were right |", "",
             "| confidence | n | hidden pass rate (95% CI) |", "|---|---|---|"]
    xs, ys, lo, hi, ns = [], [], [], [], []
    for b0, b1 in BINS:
        sel = [r for r in rows if r["verifier_verdict"] == "approve" and b0 <= (r.get("verifier_confidence") or 0) <= b1]
        if not sel:
            continue
        k = sum(r["hidden_pass"] for r in sel)
        l, h = wilson(k, len(sel))
        lines.append(f"| approve {b0}-{b1} | {len(sel)} | {k / len(sel):.0%} ({l:.0%}–{h:.0%}) |")
        xs.append(f"{b0}–{b1}")
        ys.append(k / len(sel) * 100)
        lo.append((k / len(sel) - l) * 100)
        hi.append((h - k / len(sel)) * 100)
        ns.append(len(sel))
    (OUT / "calibration.md").write_text("\n".join(lines) + "\n\n![calibration](calibration.png)\n")
    print("\n".join(lines))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.bar(xs, ys, 0.55, color=BLUE, yerr=[lo, hi], ecolor=INK2, capsize=3, error_kw={"linewidth": 1}, zorder=3)
    for i, (y, n) in enumerate(zip(ys, ns)):
        ax.text(i, 3, f"n={n}", ha="center", fontsize=8, color="white", zorder=4)
        ax.text(i, min(y + hi[i], 100) + 2, f"{y:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set_ylim(0, 110)
    ax.set_xlabel("verifier confidence when approving", color=INK2, fontsize=9)
    ax.set_ylabel("% passing hidden tests", color=INK2, fontsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)
    ax.set_title("Verifier (Nemotron) calibration: approval confidence vs hidden pass", fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "calibration.png", facecolor=SURFACE)
    print(f"wrote {OUT / 'calibration.md'} and {OUT / 'calibration.png'}")


if __name__ == "__main__":
    main()
