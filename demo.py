"""Proof of Done live demo.

  python demo.py "<one-line goal>"            full pipeline with a live timeline + receipt
  python demo.py --compare "<goal>"           solo agent vs Proof of Done, side by side
  python demo.py --task HumanEval/129         run on a benchmark task and grade against hidden tests
  add --cached to replay from the LLM response cache (venue Wi-Fi fallback)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import time

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.markup import escape
from rich.text import Text

from pod.baselines import run_solo
from pod.config import load_settings
from pod.pipeline import run_pipeline
from pod.receipt import render
from pod.sandbox import run_tests, summarize

console = Console(record=True)
ICON = {"spec": "📜", "tests": "🧪", "mutation": "🧬", "strengthen": "🔒", "verify": "🛡️ ", "decision": "⚖️ ",
        "ask": "🙋", "step": "▶"}


def live_emitter(status, t0: float):
    def emit(kind: str, text: str, **data):
        el = f"[dim]{time.time() - t0:5.1f}s[/dim]"
        if kind == "step":
            status.update(f"[bold cyan]{text}[/bold cyan]")
            return
        if kind == "receipt":
            return
        style = {"decision": "bold magenta", "ask": "bold yellow"}.get(kind, "")
        if kind == "decision" and data.get("decision") == "DONE":
            style = "bold green"
        text = escape(text)
        console.print(f"{el} {ICON.get(kind, '•')} [{style}]{text}[/{style}]" if style else f"{el} {ICON.get(kind, '•')} {text}")
        if kind == "spec":
            for a in data.get("assumptions", [])[:6]:
                console.print(f"        [dim]assumes:[/dim] {escape(a)}")
        if kind == "mutation":
            for sv in data["mutation"]["survivors"][:3]:
                console.print(f"        [dim]survived:[/dim] {escape('[' + sv['source'] + '] ' + sv['description'])}")
        if kind == "verify":
            for i in data["verifier"]["issues"][:3]:
                console.print(f"        [dim]issue:[/dim] {escape(i[:150])}")
        if kind == "tests" and data["result"]["failing_tests"]:
            for f in data["result"]["failing_tests"][:3]:
                console.print(f"        [dim]failing:[/dim] {escape(f['name'])}")
    return emit


def run_live(goal: str, signature: str | None, settings, task_id: str | None = None) -> dict:
    r = settings.roles
    console.print(Rule("[bold]Proof of Done[/bold]"))
    console.print(f"[bold]Goal:[/bold] {escape(goal.strip()[:400])}")
    console.print(f"[dim]spec/mutator: {r['spec'].model} · builder: {r['builder'].model} · "
                  f"verifier: {r['verifier'].model} ({r['verifier'].family}, different family)[/dim]\n")
    t0 = time.time()
    with console.status("starting…", spinner="dots") as status:
        rec = run_pipeline(goal, signature, settings=settings, task_id=task_id, emit=live_emitter(status, t0))
    console.print()
    console.print(render(rec))
    return rec


def compare(goal: str, signature: str | None, settings) -> None:
    console.print(Rule("[bold]Solo agent vs Proof of Done[/bold]"))
    with cf.ThreadPoolExecutor(2) as ex:
        solo_f = ex.submit(run_solo, goal, signature or "", settings=settings)
        rec = run_live(goal, signature, settings)
        solo = solo_f.result()
    # grade the solo code against the evidence Proof of Done produced (its final locked tests)
    res = run_tests(solo["code"], rec["tests"]) if rec.get("tests") else None
    solo_txt = Text()
    solo_txt.append("Claims: ", style="bold")
    solo_txt.append("DONE ✅\n" if solo["done_claimed"] else "not done\n", style="green" if solo["done_claimed"] else "yellow")
    solo_txt.append(f"{solo['llm_calls']} LLM call, {solo['wall_s']}s, no evidence\n\n")
    if res:
        bad = res["failed"] + res["errors"]
        solo_txt.append("Against Proof of Done's locked tests: ", style="bold")
        solo_txt.append(f"{summarize(res)}\n", style="red" if bad else "green")
        for f in res["failing_tests"][:5]:
            solo_txt.append(f"  ✗ {f['name']}\n", style="red")
    pod_txt = Text()
    pod_txt.append("Status: ", style="bold")
    pod_txt.append(rec["status"] + "\n", style="green" if rec["status"] == "DONE" else "yellow")
    pod_txt.append(f"Assumptions made explicit: {len(rec.get('assumptions', []))}\n")
    path = " → ".join(d["decision"] for d in rec.get("decisions", []))
    if path:
        pod_txt.append(f"Path: {path}\n", style="magenta")
    tr = rec.get("test_results") or {}
    if tr:
        pod_txt.append(f"Locked tests: {tr['passed']}/{tr['passed'] + tr['failed'] + tr['errors']} pass"
                       f" (contract v{len(rec.get('test_history', []))})\n")
    if rec.get("mutation"):
        m = rec["mutation"]
        pod_txt.append(f"Mutants killed: {m['killed']}/{m['total']}\n")
    if rec.get("verifier"):
        v = rec["verifier"]
        pod_txt.append(f"Verifier ({v['model'].split('/')[-1]}): {v['verdict']} {v['confidence']}\n")
    if rec.get("human_question"):
        pod_txt.append(f"Asks: {rec['human_question']}\n", style="yellow")
    pod_txt.append(f"{rec['llm_calls']} LLM calls, {rec['wall_s']}s, receipt saved")
    console.print(Columns([Panel(solo_txt, title="[bold]Solo agent[/bold]", border_style="red", box=box.HEAVY, width=60),
                           Panel(pod_txt, title="[bold]Proof of Done[/bold]", border_style="green", box=box.HEAVY, width=60)]))
    if res and res["failing_tests"]:
        head = "\n".join(solo["code"].splitlines()[:22])
        console.print(Panel(Syntax(head, "python", theme="ansi_dark"), title="solo agent's code (claimed done), first lines"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", nargs="?", help="one-line goal")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--task", help="benchmark task id, e.g. Mbpp/641 or HumanEval/129 (graded against hidden tests)")
    ap.add_argument("--cached", action="store_true", help="use the LLM response cache")
    ap.add_argument("--record", metavar="NAME", help="save the run to runs/recordings/NAME.svg/.txt (demo fallback)")
    a = ap.parse_args()
    try:
        _main(a, ap)
    finally:
        if a.record:
            from pod.config import RUNS
            out = RUNS / "recordings"
            out.mkdir(parents=True, exist_ok=True)
            console.save_svg(str(out / f"{a.record}.svg"), title=f"Proof of Done: {a.record}", clear=False)
            console.save_text(str(out / f"{a.record}.txt"))
            console.print(f"[dim]recorded to {out / a.record}.svg[/dim]")


def _main(a, ap) -> None:
    settings = load_settings(use_cache=a.cached)
    if a.task:
        from eval.hidden import hidden_pass
        from eval.tasks import public_task
        ds = "mbpp" if a.task.lower().startswith("mbpp") else "humaneval"
        t = public_task(a.task, ds)
        if a.compare:
            compare(t["goal"], t["signature"], settings)
            return
        rec = run_live(t["goal"], t["signature"], settings)
        h = hidden_pass(a.task, rec["code"], ds)
        console.print(f"[bold]Hidden tests (never seen by agents):[/bold] {'PASS' if h['pass'] else 'FAIL'}"
                      + ("" if h["pass"] else f"  {h}"))
        return
    if not a.goal:
        ap.error("give a goal or --task")
    (compare if a.compare else run_live)(a.goal, None, settings)


if __name__ == "__main__":
    main()
