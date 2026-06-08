"""One-off probe: does Gemini EXPLICIT context caching (CachedContent) accept the
planner's current tool set?

Re-tests the prior finding that explicit caching "400s with tools". For each
candidate model it tries to create a cache (a) WITHOUT tools as a control and
(b) WITH the 6 planner tool declarations. If the control succeeds and the
+tools attempt 400s, tools are the culprit (claim still holds). If +tools also
succeeds, the claim is stale.

Safe: short TTL and it deletes any cache it creates. Run from backend/:
    .venv/bin/python scripts/probe_gemini_explicit_cache.py
"""

from __future__ import annotations

from google import genai
from google.genai import types

from app.config import settings
from app.planner.prompts.planner import build_static_system_prompt

# The 6 planner tool NAMES the model is bound to each turn. We hand-build minimal
# genai FunctionDeclarations (name + description + one param) rather than running
# the LC->genai converter: the converter chokes on get_local_intel's injected
# field, but bind_tools (the real path) converts all 6 cleanly, so the tools ARE
# bindable. What we're testing here is whether caches.create REJECTS tools at all
# (the API-level question) — the exact param schema is irrelevant to that.
_PLANNER_TOOL_NAMES = [
    "extract_trip_fields",
    "get_specialist_advice",
    "get_local_intel",
    "search_tiles",
    "build_itinerary",
    "validate_plan",
]


def _planner_tools() -> list[types.Tool]:
    decls = [
        types.FunctionDeclaration(
            name=name,
            description=f"Planner tool {name}.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"arg": types.Schema(type=types.Type.STRING)},
            ),
        )
        for name in _PLANNER_TOOL_NAMES
    ]
    return [types.Tool(function_declarations=decls)]


def main() -> None:
    if not settings.google_api_key:
        print("GOOGLE_API_KEY not set; aborting.")
        return

    genai_tools = _planner_tools()  # list[types.Tool]
    system = build_static_system_prompt()
    # Pad contents well past the explicit-cache minimum-token floor so a min-token
    # failure can't masquerade as a tools failure.
    pad = "The traveler is planning a multi-week trip with diving and hiking. " * 600
    contents = [types.Content(role="user", parts=[types.Part(text=pad)])]

    client = genai.Client(api_key=settings.google_api_key)

    def attempt(model: str, with_tools: bool) -> None:
        cfg = types.CreateCachedContentConfig(
            system_instruction=system,
            contents=contents,
            ttl="120s",
            tools=genai_tools if with_tools else None,
        )
        label = "WITH tools " if with_tools else "no tools   "
        try:
            cache = client.caches.create(model=model, config=cfg)
            um = getattr(cache, "usage_metadata", None)
            toks = getattr(um, "total_token_count", "?") if um else "?"
            print(f"  {label} -> SUCCESS  cached_tokens={toks}  name={cache.name}")
            try:
                client.caches.delete(name=cache.name)
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 - probe wants the raw error text
            print(f"  {label} -> FAIL     {type(exc).__name__}: {str(exc)[:400]}")

    candidates = []
    for m in (settings.router_model, "gemini-2.5-flash"):
        if m and m not in candidates:
            candidates.append(m)

    print(
        f"system_instruction chars={len(system)}  tool_objs={len(genai_tools)}  "
        f"pad_chars={len(pad)}  loop_model={settings.router_model}"
    )
    for model in candidates:
        print(f"\n=== model: {model} ===")
        attempt(model, with_tools=False)
        attempt(model, with_tools=True)


if __name__ == "__main__":
    main()
