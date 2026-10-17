# NOTES: Crusoe Managed Inference findings (Step 0)

Source: `crusoecloud/crusoe-developer-hub` → `examples/hackathons/crusoe-cv-recursive-agents-hackathon/`
(`README.md` + `crusoe-cv-recursive-agents-hackathon-skill.md`, compiled Oct 13 2026). No helper code in that folder,
only docs. Anything marked *verify* is checked live against `GET /v1/models` in M0 (results appended below).

## API basics

| Item | Finding |
|---|---|
| Base URL | `https://api.inference.crusoecloud.com/v1` (old hosts `api.crusoe.ai`, `managed-inference-api-proxy...` are dead) |
| Auth | `Authorization: Bearer $CRUSOE_API_KEY`. Keys can contain `$`: single-quote them in a shell |
| OpenAI-compatible | Yes. `/v1/chat/completions`, `/v1/models`. Use the `openai` SDK with `base_url`. Non-standard fields go via `extra_body` |
| Model discovery | `GET /v1/models` returns `id`, `context_length`, `features`, `supported_parameters`, `pricing`. IDs are case-sensitive |
| Reasoning text | Comes back in `message.reasoning_content` or `message.reasoning`; counts against `max_tokens` |
| Thinking toggles | DeepSeek V4 Pro: `chat_template_kwargs: {"thinking": true}` (off by default). Nemotron Super / Lightning: `chat_template_kwargs: {"enable_thinking": false}` to disable. `{"thinking": {"type": "enabled"}}` returns 403 |
| Logprobs | Not mentioned in the docs. Checked via `supported_parameters` below |
| Prefix caching | Automatic (MemoryAlloy). Keep system prompts byte-identical, changing content at the end |

## Rate limits (per project, per model, reset every minute)

| Account | TPM / model | RPM / model |
|---|---|---|
| No payment method | 500,000 | 30 |
| Payment method on file | 2,000,000 | 600 |

429 = over TPM/RPM, 503 = shared endpoint busy. Both transient: exponential backoff from 1 s, jitter, cap ~30 s.
Response headers `x-ratelimit-remaining-requests` / `-tokens` are available. Limits are per model, so spreading roles
across different models spreads load (good for us: spec / builder / verifier are three different models).

## Models (catalog per docs; prices USD per 1M in/out)

| ID | Notes |
|---|---|
| `deepseek-ai/DeepSeek-V4-Pro` | Heavy reasoner, $1.74/$3.48. **Spec + mutator default** |
| `deepseek-ai/Deepseek-V4-Flash` | Note lowercase "s". Cheap, $0.14/$0.28 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | *verify casing* |
| `zai-org/GLM-5.3-Flash`, GLM-5.3 (*verify prefix*) | GLM-5.3 positioned as strongest open coding model |
| `google/gemma-4-31b-it` | No reasoning phase, fast, $0.14/$0.40. **Builder default** (smaller, should fail sometimes) |
| `Qwen/Qwen3.8-27B` | Thinking on by default |
| `openai/gpt-oss-120b` | $0.05/$0.20 |
| `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` | Confirmed live (docs spelling `nvidia/Nemotron-3-Super-...` 404s). **Verifier default** |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | *verify*. Cheap sub-agent model |
| `nvidia/Nemotron-3-Nano-30B-A3B` | *verify*. Cheap |
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B` | Pricing page only, *verify* |

Deprecated (do not use): Llama 3.3 70B, Kimi K2.6, GLM-5.1/5.2, DeepSeek V3, Qwen3 235B.

## Nemotron on Crusoe?

**Yes.** Several Nemotron 3 models are hosted on Crusoe, so the verifier runs on Crusoe too
(`VERIFIER_BASE_URL` = Crusoe base URL, `VERIFIER_API_KEY` falls back to `CRUSOE_API_KEY`). The NVIDIA API
(`https://integrate.api.nvidia.com/v1`) is only a fallback. Verifier family (NVIDIA Nemotron) ≠ builder family (Google Gemma).

## Role defaults (all overridable in `.env`)

| Role | Model | Temp |
|---|---|---|
| Spec | `deepseek-ai/DeepSeek-V4-Pro` | 0.2 |
| Builder | `google/gemma-4-31b-it` | 0.2 |
| Mutator | `deepseek-ai/DeepSeek-V4-Pro` | 0.7 |
| Verifier | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` | 0 |
| Condition D verifier | = builder model | 0 |

## Live checks (M0)

Run `python -m pod.check` (11:56 PT). 13 models live on the key's project:

`Qwen/Qwen3.8-27B`, `deepseek-ai/DeepSeek-V4-Pro`, `deepseek-ai/DeepSeek-V4.1-Flash`, `deepseek-ai/Deepseek-V4-Flash`,
`google/gemma-4-31b-it`, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B`,
`nvidia/NVIDIA-Nemotron-3.5-Super-VL`, `nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B`, `nvidia/Nemotron-3.5-Lightning-30B-A3B`,
`openai/gpt-oss-120b`, `zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash`.

- All four roles answered a JSON ping (spec 0.7 s, builder 1.0 s, mutator 0.5 s, verifier 0.4 s).
- **logprobs: supported** (`logprobs`, `top_logprobs` in `supported_parameters` for every role model).
- `x-ratelimit-*` headers were NOT returned on this deployment; we rely on backoff for 429/503.
- Python.org macOS Python lacks a CA bundle for `urllib`; `pod/check.py` uses `certifi` (the OpenAI SDK is unaffected).
- Nemotron ids use the `nvidia/NVIDIA-Nemotron-...` prefix for Nano/Super, but `nvidia/Nemotron-3.5-Lightning-...` for Lightning.
