"""Provider-agnostic chat call, so the consensus flow can be A/B'd across
models on identical inputs.

Only used by src/recommend.py. The split matters because the backtest runs
with web_search OFF (searching a past date is lookahead), which is exactly
the condition under which two providers see byte-identical prompts — so a
model swap isolates reasoning quality and nothing else.

Selection is by env var, so nothing in the call sites changes:

    LLM_PROVIDER=anthropic          (default)
    LLM_PROVIDER=openai  OPENAI_MODEL=<model-id>  OPENAI_API_KEY=...

Caveat worth knowing: web_search is implemented here for Anthropic only. A
request with use_search=True on any other provider raises rather than
silently producing a card built without the live prices the prompt claims
it has.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# Per-MTok input/output rates, used for the cost line in a run's summary.
# Anthropic rates are current for claude-sonnet-4-6; OpenAI rates must be
# supplied via OPENAI_INPUT_PER_MTOK / OPENAI_OUTPUT_PER_MTOK because model
# ids and prices change and guessing them would produce a wrong cost report.
RATES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    # gpt-5.4 is the deliberate A/B peer for claude-sonnet-4-6: $2.50/$15.00
    # against $3.00/$15.00, so a difference in results reflects the model and
    # not a change in spend. gpt-5.5 ($5/$30) would double output cost.
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6-luna": (0.20, 1.20),
}


@dataclass
class Reply:
    """Normalized response — text plus whatever usage the provider reported."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0
    searches: int = 0
    truncated: bool = False
    extra: dict = field(default_factory=dict)


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()


def model_id() -> str:
    p = provider()
    if p == "openai":
        m = os.environ.get("OPENAI_MODEL", "").strip()
        if not m:
            raise RuntimeError(
                "LLM_PROVIDER=openai requires OPENAI_MODEL to be set to an "
                "exact model id (no default is assumed, so the run can't "
                "silently use the wrong model)."
            )
        return m
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()


def rates(model: str) -> tuple[float, float]:
    if model in RATES:
        return RATES[model]
    try:
        return (
            float(os.environ["OPENAI_INPUT_PER_MTOK"]),
            float(os.environ["OPENAI_OUTPUT_PER_MTOK"]),
        )
    except (KeyError, ValueError):
        return (0.0, 0.0)  # unknown pricing -> report $0.00 rather than a lie


# ── Anthropic ──────────────────────────────────────────────────────────
def _anthropic(
    shared_block: str, persona_system: str, user_msg: str,
    max_tokens: int, schema: dict | None, search_tool: dict | None,
) -> Reply:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs: dict = {
        "model": model_id(),
        "max_tokens": max_tokens,
        # Shared block first with a cache breakpoint: the prefix stays
        # byte-identical across personas and across search iterations.
        "system": [
            {"type": "text", "text": shared_block,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": persona_system},
        ],
        "messages": [{"role": "user", "content": user_msg}],
    }
    if search_tool:
        kwargs["tools"] = [search_tool]
    elif schema:
        kwargs["output_config"] = {
            "format": {"type": "json_schema", "schema": schema},
        }

    r = client.messages.create(**kwargs)
    u = r.usage
    sv = getattr(u, "server_tool_use", None)
    return Reply(
        text="\n".join(
            b.text for b in r.content if getattr(b, "type", "") == "text"
        ).strip(),
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
        searches=(getattr(sv, "web_search_requests", 0) or 0) if sv else 0,
        truncated=(r.stop_reason == "max_tokens"),
    )


# ── OpenAI ─────────────────────────────────────────────────────────────
def _openai(
    shared_block: str, persona_system: str, user_msg: str,
    max_tokens: int, schema: dict | None, search_tool: dict | None,
) -> Reply:
    from openai import OpenAI

    if search_tool:
        raise NotImplementedError(
            "web_search is wired for Anthropic only. Run with use_search="
            "False (the backtest default) to A/B providers, or port the "
            "search tool before enabling it here."
        )

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    kwargs: dict = {
        "model": model_id(),
        "max_completion_tokens": max_tokens,
        # Same ordering as the Anthropic path: the large shared block leads
        # so OpenAI's automatic prefix caching can hit it too.
        "messages": [
            {"role": "system", "content": shared_block},
            {"role": "system", "content": persona_system},
            {"role": "user", "content": user_msg},
        ],
    }
    if schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "ballots", "strict": True, "schema": schema,
            },
        }

    r = client.chat.completions.create(**kwargs)
    choice = r.choices[0]
    u = r.usage
    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    total_in = getattr(u, "prompt_tokens", 0) or 0
    return Reply(
        text=(choice.message.content or "").strip(),
        input_tokens=max(0, total_in - cached),
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read=cached,
        truncated=(choice.finish_reason == "length"),
    )


_DISPATCH = {"anthropic": _anthropic, "openai": _openai}


def call(
    shared_block: str, persona_system: str, user_msg: str,
    max_tokens: int = 6000, schema: dict | None = None,
    search_tool: dict | None = None,
) -> Reply:
    p = provider()
    fn = _DISPATCH.get(p)
    if fn is None:
        raise RuntimeError(
            f"unknown LLM_PROVIDER={p!r}; expected one of "
            f"{sorted(_DISPATCH)}"
        )
    return fn(
        shared_block, persona_system, user_msg,
        max_tokens, schema, search_tool,
    )


def describe() -> str:
    try:
        m = model_id()
    except RuntimeError as e:
        return f"{provider()} (misconfigured: {e})"
    inp, out = rates(m)
    price = f"${inp}/${out} per MTok" if inp or out else "pricing unset"
    return f"{provider()}:{m} ({price})"


def json_schema_for_openai(schema: dict) -> dict:
    """OpenAI strict mode requires every property to appear in `required`."""
    s = json.loads(json.dumps(schema))

    def walk(node: dict) -> None:
        if node.get("type") == "object":
            props = node.get("properties", {})
            node["required"] = list(props)
            node["additionalProperties"] = False
            for v in props.values():
                walk(v)
        elif node.get("type") == "array" and "items" in node:
            walk(node["items"])

    walk(s)
    return s
