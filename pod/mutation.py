"""Deterministic AST mutants (no LLM cost) and the parallel mutant runner."""
from __future__ import annotations

import ast
import copy
from concurrent.futures import ThreadPoolExecutor

from .sandbox import run_tests

_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add}
_BOOL = {ast.And: ast.Or, ast.Or: ast.And}
_SYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
        ast.Add: "+", ast.Sub: "-", ast.And: "and", ast.Or: "or"}


def _sites(tree: ast.AST) -> list[tuple[str, int, int, str]]:
    """(kind, node_index, sub_index, description) for every mutable spot, in source order."""
    sites = []
    for i, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Compare):
            for j, op in enumerate(node.ops):
                if type(op) in _CMP:
                    sites.append(("cmp", i, j, f"line {line}: `{_SYM[type(op)]}` -> `{_SYM[_CMP[type(op)]]}`"))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            sites.append(("bin", i, 0, f"line {line}: `{_SYM[type(node.op)]}` -> `{_SYM[_BIN[type(node.op)]]}`"))
        elif isinstance(node, ast.BoolOp) and type(node.op) in _BOOL:
            sites.append(("bool", i, 0, f"line {line}: `{_SYM[type(node.op)]}` -> `{_SYM[_BOOL[type(node.op)]]}`"))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            sites.append(("const", i, 0, f"line {line}: constant {node.value} -> {node.value + 1}"))
    return sites


def _apply(tree: ast.AST, kind: str, idx: int, sub: int) -> ast.AST:
    t = copy.deepcopy(tree)
    node = list(ast.walk(t))[idx]
    if kind == "cmp":
        node.ops[sub] = _CMP[type(node.ops[sub])]()
    elif kind == "bin":
        node.op = _BIN[type(node.op)]()
    elif kind == "bool":
        node.op = _BOOL[type(node.op)]()
    elif kind == "const":
        node.value = node.value + 1
    return t


def _spread(sites: list, k: int) -> list:
    """Round-robin across mutation kinds so 6 mutants are not all constant bumps."""
    by_kind: dict[str, list] = {}
    for s in sites:
        by_kind.setdefault(s[0], []).append(s)
    out = []
    while len(out) < k and any(by_kind.values()):
        for kind in ("cmp", "bool", "bin", "const"):
            if by_kind.get(kind) and len(out) < k:
                out.append(by_kind[kind].pop(0))
    return out


def ast_mutants(code: str, k: int = 6) -> list[dict]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    original = ast.unparse(tree)
    out, seen = [], {original}
    for kind, idx, sub, desc in _spread(_sites(tree), k * 2):
        src = ast.unparse(_apply(tree, kind, idx, sub))
        if src in seen or not compiles(src):
            continue
        seen.add(src)
        out.append({"source": "ast", "description": desc, "code": src})
        if len(out) >= k:
            break
    return out


def compiles(src: str) -> bool:
    try:
        compile(src, "<mutant>", "exec")
        return True
    except SyntaxError:
        return False


def normalized(src: str) -> str:
    try:
        return ast.unparse(ast.parse(src))
    except SyntaxError:
        return src


def dedupe(original: str, mutants: list[dict]) -> list[dict]:
    """Drop mutants that do not compile or are identical to the original (or to each other)."""
    seen = {normalized(original)}
    out = []
    for m in mutants:
        n = normalized(m["code"])
        if n in seen or not compiles(m["code"]):
            continue
        seen.add(n)
        out.append(m)
    return out


def run_mutants(mutants: list[dict], test_code: str, sandbox: str = "local", timeout: float = 8) -> dict:
    """Killed = any test fails, errors, or times out."""
    def one(m):
        r = run_tests(m["code"], test_code, timeout=timeout, kind=sandbox)
        killed = r["failed"] > 0 or r["errors"] > 0 or r["timed_out"]
        killers = [t["name"] for t in r["failing_tests"]][:3]
        return {**m, "killed": killed, "killed_by": killers}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, mutants))
    killed = sum(r["killed"] for r in results)
    total = len(results)
    return {
        "total": total,
        "killed": killed,
        "kill_rate": (killed / total) if total else 1.0,
        "survivors": [{"source": r["source"], "description": r["description"], "code": r["code"]} for r in results if not r["killed"]],
        "results": [{"source": r["source"], "description": r["description"], "killed": r["killed"], "killed_by": r["killed_by"]} for r in results],
    }
