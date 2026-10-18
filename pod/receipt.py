"""Receipt: the evidence bundle every run ends with (JSON on disk + a rich panel)."""
from __future__ import annotations

import json

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import RUNS

RECEIPTS = RUNS / "receipts"


def save_receipt(r: dict) -> str:
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    path = RECEIPTS / f"{r['id'].replace('/', '_')}.json"
    path.write_text(json.dumps(r, indent=2))
    return str(path)


def render(r: dict) -> Panel:
    status = r["status"]
    color = {"DONE": "green", "ASK_HUMAN": "yellow"}.get(status, "red")
    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold")
    head.add_column()
    head.add_row("Goal", Text(r["goal"].strip()[:300]))
    head.add_row("Status", Text(status if status != "ASK_HUMAN" else "NOT DONE: asking human", style=f"bold {color}"))
    if r.get("human_question"):
        head.add_row("Question", Text(r["human_question"], style="yellow"))
    tr = r.get("test_results") or {}
    if tr:
        total = tr["passed"] + tr["failed"] + tr["errors"]
        head.add_row("Tests", f"{tr['passed']}/{total} pass" + (f"  failing: {', '.join(tr['failing'][:4])}" if tr.get("failing") else ""))
    head.add_row("Tests sha256", (r.get("tests_sha256") or "-")[:16] + "…  (locked; builder cannot edit)")
    m = r.get("mutation")
    if m:
        line = f"{m['killed']}/{m['total']} mutants killed ({m['kill_rate']:.0%})"
        if m.get("kill_rate_before") is not None and m["kill_rate_before"] != m["kill_rate"]:
            line += f"  (initially {m['kill_rate_before']:.0%})"
        if m.get("equivalent_excluded"):
            line += f"  ({m['equivalent_excluded']} equivalent excluded)"
        head.add_row("Mutation", line)
        for sv in m.get("survivors", [])[:3]:
            head.add_row("", Text(f"survived: {sv}"[:110], style="dim"))
    v = r.get("verifier")
    if v:
        head.add_row("Verifier", f"{v['model']}: {v['verdict']} ({v['confidence']})")
        for i in v.get("issues", [])[:3]:
            head.add_row("", Text(f"- {i}"[:140], style="dim"))
    for o in r.get("verifier_objections", []):
        state = {True: "PROVEN", False: "unproven (logged, ignored)", None: "unchecked (unparseable reply)"}[o["proven"]]
        line = (f"round {o['round']}: {o['verdict']}, code fails {len(o['failed'])}/{len(o['counterexamples'])} "
                f"counterexamples -> {state}, {o['decision']}")
        head.add_row("Evidence" if o["round"] == 1 else "", Text(line, style="bold" if o["proven"] else "dim"))
    head.add_row("Cost", f"{r.get('llm_calls', 0)} LLM calls, {r.get('total_tokens', 0):,} tokens, {r.get('wall_s', 0)}s")

    parts = [head]
    if r.get("assumptions"):
        a = Text("\nAssumptions (made explicit, each has a test):\n", style="bold")
        for x in r["assumptions"][:8]:
            a.append(f"  • {x}\n", style="")
        parts.append(a)
    if len(r.get("test_history", [])) > 1 or r.get("test_history"):
        th = Table(box=box.SIMPLE, show_header=True, header_style="bold", title="Test contract history", title_justify="left")
        for c in ("v", "sha256", "tests", "asserts", "reason"):
            th.add_column(c)
        for h in r["test_history"]:
            th.add_row(str(h["version"]), h["sha256"][:10], str(h["n_tests"]), str(h["n_asserts"]), h["reason"][:70])
        parts.append(th)
    tl = Table(box=box.SIMPLE, header_style="bold", title="Timeline", title_justify="left")
    for c in ("step", "model", "s", "tokens"):
        tl.add_column(c)
    for t in r.get("timeline", []):
        tl.add_row(t["step"], t["model"].split("/")[-1], f"{t['duration_s']:.1f}", f"{t['tokens']:,}")
    parts.append(tl)
    return Panel(Group(*parts), title=f"[bold]Proof of Done receipt[/bold]  {r['id']}", border_style=color, box=box.HEAVY)
