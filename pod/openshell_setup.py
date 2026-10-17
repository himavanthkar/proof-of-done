"""Create the persistent OpenShell sandbox used by SANDBOX=openshell:  python -m pod.openshell_setup

Requires the OpenShell CLI + a running gateway (macOS: Homebrew formula from the NVIDIA/OpenShell release, gateway with
OPENSHELL_COMPUTE_DRIVER=vm, e2fsprogs installed). The sandbox has no network, so pytest and its pure-Python
dependencies are uploaded from this venv.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = os.environ.get("OPENSHELL_SANDBOX", "pod-sbx")
IMAGE = os.environ.get("OPENSHELL_IMAGE", "python:3.12-slim")
PKGS = ["_pytest", "pytest", "pluggy", "iniconfig", "packaging", "pygments", "py.py"]


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(args))
    return subprocess.run(args, check=check, text=True, capture_output=True, cwd=tempfile.gettempdir())


def main() -> int:
    if not shutil.which("openshell"):
        print("openshell CLI not found; see README (OpenShell section)")
        return 1
    if NAME not in sh("openshell", "sandbox", "list").stdout:
        r = sh("openshell", "sandbox", "create", "--name", NAME, "--from", IMAGE, "--no-tty", "--detach", "--",
               "sleep", "infinity", check=False)
        print(r.stdout[-800:], r.stderr[-800:])
    import pytest
    site = Path(pytest.__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as d:
        vend = Path(d) / "podvendor"
        vend.mkdir()
        for p in PKGS:
            src = site / p
            if src.is_dir():
                shutil.copytree(src, vend / p, ignore=shutil.ignore_patterns("__pycache__"))
            elif src.exists():
                shutil.copy(src, vend / p)
        for dist in site.glob("*.dist-info"):
            if dist.name.split("-")[0].lower() in {"pytest", "pluggy", "iniconfig", "packaging", "pygments"}:
                shutil.copytree(dist, vend / dist.name)
        sh("openshell", "sandbox", "upload", "--no-git-ignore", NAME, str(vend), "/sandbox/vendor")
    r = sh("openshell", "sandbox", "exec", NAME, "--no-tty", "--no-login-shell", "--", "sh", "-c",
           "PYTHONPATH=/sandbox/vendor/podvendor python3 -m pytest --version")
    print(r.stdout.strip() or r.stderr.strip())
    from .sandbox import OpenShellSandbox
    ok = OpenShellSandbox(NAME).run_tests("def f():\n    return 1\n", "from solution import f\ndef test_f(): assert f() == 1\n")
    print("smoke test:", "PASS" if ok["passed"] == 1 else ok)
    return 0 if ok["passed"] == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
