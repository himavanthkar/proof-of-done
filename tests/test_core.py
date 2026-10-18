"""Offline tests for the deterministic parts (no API key needed): decision step, sandbox, mutants, JSON parsing."""
from pod.llm import extract_json
from pod.mutation import ast_mutants, dedupe, run_mutants
from pod.pipeline import ASK_HUMAN, DONE, FIX_TEST, REPLAN, RETRY, Facts, decide
from pod.sandbox import run_tests

SOL = "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n"
TESTS = ("from solution import clamp\n"
         "def test_mid(): assert clamp(5, 0, 10) == 5\n"
         "def test_lo(): assert clamp(-1, 0, 10) == 0\n"
         "def test_hi(): assert clamp(11, 0, 10) == 10\n")


def test_decide_paths():
    a, b = frozenset({"test_a"}), frozenset({"test_b"})
    assert decide(Facts(False, 0, 2, a, None))[0] == RETRY
    assert decide(Facts(False, 1, 2, a, a))[0] == REPLAN
    assert decide(Facts(False, 1, 2, a, a, replans_used=1))[0] == RETRY
    assert decide(Facts(False, 2, 2, a, b, 1))[0] == ASK_HUMAN
    assert decide(Facts(False, 1, 2, a, a, disputes=1))[0] == FIX_TEST
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="approve"))[0] == DONE
    assert decide(Facts(True, 0, 2, kill_rate=0.5, verdict="approve"))[0] == ASK_HUMAN
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject"))[0] == RETRY
    assert decide(Facts(True, 2, 2, kill_rate=0.9, verdict="reject"))[0] == ASK_HUMAN
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="approve", disputes=1))[0] == FIX_TEST
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="approve", disputes=1, dispute_fix_used=True))[0] == DONE
    # a rejection only the human can resolve (goal ambiguity) skips pointless builder retries
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", fix_by="human"))[0] == ASK_HUMAN


def test_done_requires_all_three_signals():
    for kill, verdict in [(0.79, "approve"), (1.0, "reject")]:
        assert decide(Facts(True, 0, 2, kill_rate=kill, verdict=verdict))[0] != DONE


def test_sandbox_pass_fail_timeout_and_no_keys():
    assert run_tests(SOL, TESTS)["passed"] == 3
    r = run_tests(SOL.replace("return lo", "return hi"), TESTS)
    assert r["failed"] == 1 and r["failing_tests"][0]["name"] == "test_lo"
    assert run_tests("def clamp(x, lo, hi):\n    while True: pass\n", TESTS, timeout=3)["timed_out"]
    leak = "import os\ndef clamp(x, lo, hi):\n    return len([k for k in os.environ if 'KEY' in k])\n"
    t = "from solution import clamp\ndef test_env(): assert clamp(0, 0, 0) == 0\n"
    assert run_tests(leak, t)["passed"] == 1  # no *KEY* env vars visible inside the sandbox


def test_mutants_compile_differ_and_get_killed():
    ms = dedupe(SOL, ast_mutants(SOL))
    assert ms and all(m["code"] != SOL for m in ms)
    strong = TESTS + "def test_edges():\n    assert clamp(0, 0, 10) == 0\n    assert clamp(10, 0, 10) == 10\n"
    assert run_mutants(ms, strong)["total"] == len(ms)


def test_extract_json_tolerates_fences_and_bad_escapes():
    assert extract_json('```json\n{"a": 1,}\n```') == {"a": 1}
    assert extract_json('prose {"issues": ["uses \\(x\\)"]} more') == {"issues": ["uses \\(x\\)"]}
    assert extract_json("no json here") is None


def _openshell_ready() -> bool:
    import shutil
    import subprocess
    if not shutil.which("openshell"):
        return False
    r = subprocess.run(["openshell", "sandbox", "list"], capture_output=True, text=True)
    return r.returncode == 0 and "pod-sbx" in r.stdout and "Ready" in r.stdout


def test_openshell_sandbox_same_verdicts_as_local():
    import pytest
    if not _openshell_ready():
        pytest.skip("OpenShell CLI / sandbox pod-sbx not available (python -m pod.openshell_setup)")
    from pod.sandbox import OpenShellSandbox
    sb = OpenShellSandbox()
    assert sb.run_tests(SOL, TESTS)["passed"] == 3
    r = sb.run_tests(SOL.replace("return lo", "return hi"), TESTS)
    assert r["failed"] == 1 and r["failing_tests"][0]["name"] == "test_lo"
    assert sb.run_tests("def clamp(x, lo, hi):\n    while True: pass\n", TESTS, timeout=3)["timed_out"]
    net = ("import urllib.request\ndef clamp(x, lo, hi):\n    try:\n        urllib.request.urlopen('https://example.com', timeout=3)\n"
           "        return 1\n    except Exception:\n        return 0\n")
    assert sb.run_tests(net, "from solution import clamp\ndef test_net(): assert clamp(0, 0, 0) == 0\n")["passed"] == 1
    tamper = "open('test_solution.py', 'w').write('def test_x(): pass\\n')\n" + SOL
    assert sb.run_tests(tamper, TESTS)["tests_intact"] is False


# ------------------------------------------------------------------ verifier counterexamples (executable objections)

def test_parse_counterexamples_keeps_only_well_formed():
    from pod.agents.verifier import parse_counterexamples
    cxs = parse_counterexamples([
        {"args": [1, 2], "expected": 3, "why": "sum\n of two"},
        {"args": 5, "expected": None},                      # scalar args are wrapped; null is a real expected value
        {"args": [-1], "raises": "ValueError"},
        {"args": [1, 2], "expected": 3, "why": "duplicate"},
        {"expected": 3}, "not a dict", {"args": [1]},       # missing args / missing expected
        {"args": [float("inf")], "expected": 0},            # not representable as a Python literal
    ])
    assert cxs == [{"args": [1, 2], "expected": 3, "why": "sum of two"}, {"args": [5], "expected": None, "why": ""},
                   {"args": [-1], "raises": "ValueError", "why": ""}]
    assert len(parse_counterexamples([{"args": [i], "expected": i} for i in range(9)])) == 5
    assert parse_counterexamples(None) == [] and parse_counterexamples("x") == []


def test_counterexample_check_proves_only_real_failures():
    from pod.pipeline import check_counterexamples
    c = check_counterexamples(SOL, "clamp", [{"args": [5, 0, 10], "expected": 5, "why": "inside"},
                                             {"args": [-1, 0, 10], "expected": -1, "why": "wrong on purpose"}])
    assert c["proven"] and c["failed"] == [2]
    assert [x["result"] for x in c["proposed"]] == ["pass", "fail"] and "returned 0" in c["proposed"][1]["message"]
    assert "def test_verifier_cx_r1_2" in c["tests"] and "def test_verifier_cx_r1_1" not in c["tests"]
    assert not check_counterexamples(SOL, "clamp", [{"args": [5, 0, 10], "expected": 5}])["proven"]
    assert check_counterexamples(SOL, "clamp", []) == {"proposed": [], "failed": [], "proven": False, "tests": ""}
    # a broken harness (wrong function name) is never evidence against the code
    bad = check_counterexamples(SOL, "no_such_fn", [{"args": [-1, 0, 10], "expected": -1}])
    assert not bad["proven"] and bad["proposed"][0]["result"] == "invalid"


def test_counterexample_json_values_compare_structurally():
    from pod.pipeline import check_counterexamples
    code = ("def f(t, k):\n"
            "    if k == 'tuple': return tuple(sorted(t))\n"            # tuple result vs JSON list
            "    if k == 'set': return set(t)\n"                        # set result vs JSON list (any order)
            "    if k == 'dict': return {x: x * x for x in t}\n"        # int keys vs JSON string keys
            "    if k == 'float': return sum(t) / 3\n"                  # float tolerance
            "    if k == 'needs_tuples': return [p + (0,) for p in t]\n"  # JSON lists must be retried as tuples
            "    if k == 'raise': raise ValueError('bad')\n"
            "    return None\n")
    ok = [{"args": [[3, 1, 2], "tuple"], "expected": [1, 2, 3]}, {"args": [[3, 1, 3], "set"], "expected": [1, 3]},
          {"args": [[2, 3], "dict"], "expected": {"2": 4, "3": 9}}, {"args": [[0.1, 0.2, 0.0], "float"], "expected": 0.1},
          {"args": [[[1, 2]], "needs_tuples"], "expected": [[1, 2, 0]]}, {"args": [[], "raise"], "raises": "ValueError"},
          {"args": [[], "none"], "expected": None}]
    c = check_counterexamples(code, "f", ok)
    assert not c["proven"], [x for x in c["proposed"] if x["result"] != "pass"]
    wrong = [{"args": [[3, 1, 2], "tuple"], "expected": [3, 2, 1]}, {"args": [[], "raise"], "raises": "KeyError"},
             {"args": [[], "none"], "raises": "ValueError"}, {"args": [[2], "dict"], "expected": {"2": 5}}]
    assert check_counterexamples(code, "f", wrong)["failed"] == [1, 2, 3, 4]


def test_counterexample_timeout_is_isolated():
    from pod.pipeline import check_counterexamples
    code = "def g(n):\n    while n == 7:\n        pass\n    return n\n"
    c = check_counterexamples(code, "g", [{"args": [1], "expected": 1}, {"args": [7], "expected": 7}])
    assert c["failed"] == [2] and c["proposed"][1]["message"] == "timed out" and c["proposed"][0]["result"] == "pass"


def test_decide_requires_evidence_for_rejections():
    # unproven: the code passes every counterexample -> the rejection is logged, not acted on
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", proven=False))[0] == DONE
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", fix_by="human", proven=False))[0] == DONE
    assert decide(Facts(True, 0, 2, kill_rate=0.5, verdict="reject", proven=False))[0] == ASK_HUMAN
    # proven: the code fails a goal-derived counterexample -> builder retry, even if the verifier blamed the goal
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", proven=True))[0] == RETRY
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", fix_by="human", proven=True))[0] == RETRY
    assert decide(Facts(True, 2, 2, kill_rate=0.9, verdict="reject", proven=True))[0] == ASK_HUMAN
    # approval is unaffected; an unparseable verifier reply (proven=None) keeps the old blocking behaviour
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="approve", proven=False))[0] == DONE
    assert decide(Facts(True, 0, 2, kill_rate=0.9, verdict="reject", proven=None))[0] == RETRY


def _stub_pipeline(monkeypatch, codes: list[str], verdicts: list[dict]):
    """Run the real pipeline loop with the four LLM agents replaced by scripted replies."""
    from pod import pipeline as P
    from pod.config import load_settings
    calls = {"build": [], "verify": 0}

    def build(role, goal, sig, tests, **k):
        calls["build"].append(k.get("feedback"))
        return {"code": codes[len(calls["build"]) - 1], "notes": ""}

    def verify(*a, **k):
        calls["verify"] += 1
        base = {"model": "stub", "verdict": "approve", "confidence": 90, "issues": [], "disputed_tests": [],
                "equivalent_mutants": [], "fix_by": "builder", "counterexamples": [], "parsed": True}
        return base | verdicts[calls["verify"] - 1]

    monkeypatch.setattr(P.S, "write_spec", lambda *a, **k: {"function_name": "clamp", "signature": "def clamp(x, lo, hi):",
                                                          "assumptions": ["bounds are inclusive"], "tests": TESTS})
    monkeypatch.setattr(P.B, "build", build)
    monkeypatch.setattr(P.M, "make_mutants", lambda *a, **k: [])
    monkeypatch.setattr(P.V, "verify", verify)
    monkeypatch.setattr(P.S, "ask_human", lambda *a, **k: {"question": "?", "assumption": ""})
    r = P.run_pipeline("Clamp x into [lo, hi].", "def clamp(x, lo, hi):", settings=load_settings(use_cache=False),
                       task_id="stub", save=False)
    return r, calls


BUGGY = SOL.replace("    return x\n", "    return 0 if x == 7 else x\n")  # passes the locked tests, wrong at x == 7


def test_pipeline_proven_objection_locks_counterexample_and_retries(monkeypatch):
    cx = {"args": [7, 0, 10], "expected": 7, "why": "7 is inside the range"}
    r, calls = _stub_pipeline(monkeypatch, [BUGGY, SOL], [{"verdict": "reject", "counterexamples": [cx]}, {}])
    assert r["status"] == "DONE" and r["attempts"] == 2
    assert r["test_history"][-1]["reason"].startswith("verifier counterexample: 7 is inside the range")
    assert "def test_verifier_cx_r1_1" in r["tests"] and r["test_results"]["failed"] == 0
    o = r["verifier_objections"][0]
    assert o["proven"] and o["failed"] == [1] and o["decision"] == RETRY and o["code"] == BUGGY
    assert "test_verifier_cx_r1_1" in calls["build"][1]  # the builder is told which locked counterexample it failed


def test_pipeline_unproven_objection_is_logged_not_retried(monkeypatch):
    for cxs in ([{"args": [5, 0, 10], "expected": 5, "why": "the code already does this"}], []):
        r, calls = _stub_pipeline(monkeypatch, [SOL], [{"verdict": "reject", "fix_by": "human", "counterexamples": cxs}])
        assert r["status"] == "DONE" and r["attempts"] == 1 and len(calls["build"]) == 1
        assert len(r["test_history"]) == 1  # contract untouched
        o = r["verifier_objections"][0]
        assert o["proven"] is False and o["decision"] == DONE and "unproven" in r["decisions"][-1]["reason"]
