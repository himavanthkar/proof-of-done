"""Hidden ground truth: differential testing vs canonical_solution on base_input + plus_input.

Never imported from pod/. Candidate and canonical each run in a stripped subprocess with a timeout; inputs are
deep-copied before every call; floats compared with atol; an exception is a mismatch unless canonical also raised.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

from pod.config import RUNS

from .tasks import _dataset

CANON_DIR = RUNS / "cache" / "canonical"

_RUNNER = r'''
import copy, pickle, sys, json, math
sys.setrecursionlimit(10000)
src = open("candidate.py").read()
ns = {"__name__": "candidate"}
try:
    exec(compile(src, "candidate.py", "exec"), ns)
    fn = ns[sys.argv[1]]
except Exception as e:
    print(json.dumps({"load_error": repr(e)[:300]})); sys.exit(0)
inputs = pickle.load(open("inputs.pkl", "rb"))
mode = sys.argv[2]
outs = []
if mode == "compare":
    expected = pickle.load(open("expected.pkl", "rb"))
    atol = float(sys.argv[3])

def close(a, b, atol):
    if isinstance(b, bool) or isinstance(a, bool):
        return a == b and type(a) == type(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and (isinstance(a, float) or isinstance(b, float)):
        if math.isnan(a) and math.isnan(b): return True
        return abs(a - b) <= max(atol, 1e-6) + 1e-7 * abs(b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return type(a) == type(b) and len(a) == len(b) and all(close(x, y, atol) for x, y in zip(a, b))
    return a == b

for i, args in enumerate(inputs):
    try:
        out = ("ok", fn(*copy.deepcopy(args)))
    except BaseException as e:
        out = ("exc", type(e).__name__)
    if mode == "record":
        outs.append(out)
    else:
        exp = expected[i]
        ok = (exp[0] == "exc" and out[0] == "exc") or (exp[0] == "ok" and out[0] == "ok" and close(out[1], exp[1], atol))
        if not ok:
            print(json.dumps({"pass": False, "index": i, "input": repr(args)[:200], "got": repr(out)[:200], "expected": repr(exp)[:200]}))
            sys.exit(0)
if mode == "record":
    pickle.dump(outs, open("expected.pkl", "wb"))
    print(json.dumps({"recorded": len(outs)}))
else:
    print(json.dumps({"pass": True, "n": len(inputs)}))
'''


def _run(code: str, entry: str, inputs: list, mode: str, expected: list | None = None, atol: float = 0,
         timeout: float = 60) -> tuple[dict, list | None]:
    with tempfile.TemporaryDirectory(prefix="pod_hidden_") as d:
        p = Path(d)
        (p / "candidate.py").write_text(code)
        (p / "runner.py").write_text(_RUNNER)
        with open(p / "inputs.pkl", "wb") as f:
            pickle.dump(inputs, f)
        if expected is not None:
            with open(p / "expected.pkl", "wb") as f:
                pickle.dump(expected, f)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": d, "PYTHONHASHSEED": "0"}
        try:
            r = subprocess.run([sys.executable, "runner.py", entry, mode, str(atol)], cwd=p, env=env,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"pass": False, "reason": f"timeout {timeout}s"}, None
        line = (r.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            res = json.loads(line)
        except json.JSONDecodeError:
            res = {"pass": False, "reason": (r.stderr or r.stdout)[-300:]}
        rec = None
        if mode == "record" and (p / "expected.pkl").exists():
            rec = pickle.loads((p / "expected.pkl").read_bytes())
        return res, rec


def canonical_outputs(task_id: str, dataset: str = "humaneval") -> list:
    CANON_DIR.mkdir(parents=True, exist_ok=True)
    f = CANON_DIR / (task_id.replace("/", "_") + ".pkl")
    if f.exists():
        return pickle.loads(f.read_bytes())
    t = _dataset(dataset)[task_id]
    inputs = t["base_input"] + t["plus_input"]
    res, rec = _run(t["prompt"] + t["canonical_solution"], t["entry_point"], inputs, "record", timeout=300)
    if rec is None:
        raise RuntimeError(f"canonical failed for {task_id}: {res}")
    f.write_bytes(pickle.dumps(rec))
    return rec


def hidden_pass(task_id: str, code: str, dataset: str = "humaneval", timeout: float = 60) -> dict:
    """{'pass': bool, ...mismatch details}"""
    if not code or not code.strip():
        return {"pass": False, "reason": "no code"}
    t = _dataset(dataset)[task_id]
    expected = canonical_outputs(task_id, dataset)
    res, _ = _run(code, t["entry_point"], t["base_input"] + t["plus_input"], "compare", expected,
                  float(t.get("atol") or 0), timeout)
    if "load_error" in res:
        return {"pass": False, "reason": res["load_error"]}
    res.setdefault("pass", False)
    return res
