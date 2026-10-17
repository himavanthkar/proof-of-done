"""Run a pytest file against a solution in an isolated sandbox.

run_tests(solution_code, test_code, timeout=10) -> {passed, failed, errors, total, failing_tests, timed_out, output}
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


class LocalSandbox:
    """Temp dir + subprocess pytest, stripped environment (no API keys), killed on timeout."""

    name = "local"

    def run_tests(self, solution_code: str, test_code: str, timeout: float = 10) -> dict:
        with tempfile.TemporaryDirectory(prefix="pod_sbx_") as d:
            p = Path(d)
            (p / "solution.py").write_text(solution_code)
            (p / "test_solution.py").write_text(test_code)
            home = p / "home"
            home.mkdir()
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PYTHONPATH": str(p),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                   "--junitxml=report.xml", "test_solution.py"]
            proc = subprocess.Popen(cmd, cwd=p, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
                return {"passed": 0, "failed": 0, "errors": 1, "total": 0, "timed_out": True,
                        "failing_tests": [{"name": "<timeout>", "message": f"test run exceeded {timeout}s"}],
                        "output": "TIMEOUT"}
            res = _parse_junit(p / "report.xml", out)
            # tamper check: the locked test file must be byte-identical after the run
            res["tests_intact"] = (p / "test_solution.py").exists() and (p / "test_solution.py").read_text() == test_code
            return res


def _parse_junit(report: Path, out: str) -> dict:
    res = {"passed": 0, "failed": 0, "errors": 0, "total": 0, "timed_out": False, "failing_tests": [],
           "output": out[-3000:]}
    if not report.exists():
        res["errors"] = 1
        res["failing_tests"].append({"name": "<collection>", "message": out[-1500:]})
        return res
    root = ET.parse(report).getroot()
    for tc in root.iter("testcase"):
        res["total"] += 1
        bad = tc.find("failure")
        kind = "failed"
        if bad is None:
            bad = tc.find("error")
            kind = "errors"
        if bad is None:
            if tc.find("skipped") is None:
                res["passed"] += 1
            continue
        res[kind] += 1
        msg = (bad.get("message") or "") + "\n" + (bad.text or "")
        res["failing_tests"].append({"name": tc.get("name", "?"), "message": msg.strip()[:800]})
    if res["total"] == 0:  # collection error (e.g. import failure) produces no testcases on some versions
        res["errors"] = 1
        res["failing_tests"].append({"name": "<collection>", "message": out[-1500:]})
    return res


class OpenShellSandbox:
    """NVIDIA OpenShell sandbox (stretch). Same interface; selected by SANDBOX=openshell."""

    name = "openshell"

    def run_tests(self, solution_code: str, test_code: str, timeout: float = 10) -> dict:
        raise NotImplementedError("OpenShell sandbox not available; set SANDBOX=local")


def get_sandbox(kind: str = "local"):
    return OpenShellSandbox() if kind == "openshell" else LocalSandbox()


def run_tests(solution_code: str, test_code: str, timeout: float = 10, kind: str = "local") -> dict:
    return get_sandbox(kind).run_tests(solution_code, test_code, timeout)


def failure_signature(result: dict) -> frozenset:
    return frozenset(t["name"] for t in result.get("failing_tests", []))


def summarize(result: dict) -> str:
    tot = result["passed"] + result["failed"] + result["errors"]
    s = f"{result['passed']}/{tot} pass"
    if result["timed_out"]:
        s += " (timed out)"
    return s
