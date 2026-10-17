"""M0 connectivity check: `python -m pod.check`. Lists models, confirms role ids, pings each role with a JSON task."""
from __future__ import annotations

import json
import sys

import ssl
import urllib.request

import certifi
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .llm import chat, client_for, extract_json

console = Console()


def main() -> int:
    s = load_settings()
    roles = s.roles
    spec = roles["spec"]
    if not spec.api_key:
        console.print("[red]CRUSOE_API_KEY is empty in .env[/red]")
        return 1

    req = urllib.request.Request(f"{spec.base_url}/models", headers={"Authorization": f"Bearer {spec.api_key}"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as resp:
        models = {m["id"]: m for m in json.loads(resp.read())["data"]}
    console.print(f"[bold]{len(models)} models on Crusoe:[/bold] " + ", ".join(sorted(models)))
    if "--models" in sys.argv:
        for mid in sorted(models):
            m = models[mid]
            console.print(f"  {mid}: ctx={m.get('context_length')} params={m.get('supported_parameters')}")

    t = Table(title="Role check")
    for col in ("role", "model", "on crusoe", "logprobs", "reply", "tokens", "latency"):
        t.add_column(col)
    ok = True
    for name, role in roles.items():
        meta = models.get(role.model) if role.base_url == spec.base_url else None
        params = (meta or {}).get("supported_parameters") or []
        try:
            rep = chat(role, [{"role": "user", "content": 'Reply with only this JSON: {"ok": true, "sum": 2+3 evaluated}'}],
                       max_tokens=512, step="m0-ping")
            data = extract_json(rep.text)
            good = bool(data and data.get("ok") is True)
            ok &= good
            t.add_row(name, role.model, "yes" if meta else ("n/a" if role.base_url != spec.base_url else "[red]NO[/red]"),
                      str("logprobs" in params), json.dumps(data) if data else rep.text[:60], str(rep.tokens), f"{rep.latency_s:.1f}s")
        except Exception as e:  # noqa: BLE001
            ok = False
            t.add_row(name, role.model, "yes" if meta else "[red]NO[/red]", "-", f"[red]{e}[/red]"[:120], "-", "-")
    console.print(t)

    raw = client_for(spec).chat.completions.with_raw_response.create(
        model=roles["builder"].model, messages=[{"role": "user", "content": "hi"}], max_tokens=8)
    console.print("rate limit headers:", {k: v for k, v in raw.headers.items() if k.startswith("x-ratelimit")})
    console.print("[green]M0 OK[/green]" if ok else "[red]M0 FAILED[/red]")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
