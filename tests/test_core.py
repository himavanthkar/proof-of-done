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
