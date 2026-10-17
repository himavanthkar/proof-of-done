"""Shared helper: one chat call -> parsed JSON (tolerates fences), with a python-fence fallback for code fields."""
from __future__ import annotations

from ..config import Role
from ..llm import Tracker, chat, code_fences, extract_json


def ask_json(role: Role, system: str, user: str, *, tracker: Tracker | None, step: str, max_tokens: int = 4096,
             use_cache: bool = False, code_key: str | None = None, force: bool = False) -> tuple[dict, str]:
    """Returns (parsed_dict, raw_text). If JSON parsing fails and code_key is set, the first python fence fills it."""
    if force and tracker:
        tracker.max_calls = max(tracker.max_calls, tracker.calls + 1)
        tracker.wall_clock_s = max(tracker.wall_clock_s, tracker.elapsed() + 60)
    reply = chat(role, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                 tracker=tracker, step=step, max_tokens=max_tokens, use_cache=use_cache)
    data = extract_json(reply.text) or {}
    if code_key and not (isinstance(data.get(code_key), str) and data[code_key].strip()):
        fences = code_fences(reply.text, "python")
        if fences:
            data[code_key] = max(fences, key=len)
    return data, reply.text
