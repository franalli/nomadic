"""
Phase 0 de-risk spike (BLOCKING gate) for the create_agent migration.

Probes the three statically-unverifiable facts the whole agentic redesign rests on,
against LIVE gemini-2.5-flash (settings.router_model):

  1. PARALLEL TOOL CALLS  -- does Flash emit >=2 tool calls in ONE AIMessage?
  2. TOKEN INTERLEAVING    -- does Flash narrate prose on a tool-calling turn?
  3. ARGS-FIRST DATA       -- do batched fetch tools receive the right destination?

Run:  backend/.venv/bin/python -m tests.spike_agent_parallel
(needs GOOGLE_API_KEY in backend/.env)

This is a probe, not a unit test -- it prints observations and a PASS/FAIL verdict.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.tools import tool

from app.config import settings
from app.planner.llm_factory import get_llm_by_model

# ---------------------------------------------------------------------------
# Stub tools -- mirror the recovered args-first signatures, record received args
# ---------------------------------------------------------------------------

RECEIVED: dict[str, dict[str, Any]] = {}


@tool
async def extract_trip_fields(
    user_message: str,
    current_destination: str = "",
    current_origin: str = "",
) -> dict:
    """Record and normalize trip fields the traveler stated (destination, origin,
    dates, travelers). Call this FIRST when the traveler gives any trip detail."""
    RECEIVED["extract_trip_fields"] = {"user_message": user_message}
    return {"destination": "Bali", "origin": "London", "duration_days": 7, "adults": 2}


@tool
async def search_tiles(
    destination: str,
    start_date: str = "",
    end_date: str = "",
    origin: str = "",
    types: str = "flights,hotels,activities",
) -> dict:
    """Fetch live flights/hotels/activities for the destination. Pass the
    destination explicitly."""
    RECEIVED["search_tiles"] = {"destination": destination, "origin": origin, "types": types}
    return {"hotels": 6, "flights": 4, "activities": 8}


@tool
async def get_specialist_advice(topic: str, destination: str = "") -> dict:
    """Plan an activity-led pursuit (e.g. diving, hiking). Pass the pursuit as
    `topic` and the destination explicitly."""
    RECEIVED.setdefault("get_specialist_advice", {})[topic] = {"destination": destination}
    return {"topic": topic, "feasibility": "feasible", "activities": 5}


@tool
async def get_local_intel(destination: str) -> dict:
    """Best neighborhoods, airport transfers, getting around for the destination."""
    RECEIVED["get_local_intel"] = {"destination": destination}
    return {"neighborhoods": ["Seminyak", "Ubud"]}


SYSTEM_PROMPT = (
    "You are the planning orchestrator for Nomadic, a travel-planning product. You turn a "
    "traveler's message into a bookable trip by calling tools. Nothing happens unless you call "
    "a tool.\n\n"
    "RUN INDEPENDENT WORK IN PARALLEL -- this is your most important rule. When tool calls do "
    "not depend on each other, emit them TOGETHER in a single response. Once a destination and "
    "dates are known, search_tiles, get_local_intel, and get_specialist_advice are independent "
    "-- fire them in ONE turn. Never split independent calls across turns.\n\n"
    "When the traveler states a trip detail, call extract_trip_fields first. Then fire the "
    "independent fetches in parallel. Do not narrate or write any prose before or between tool "
    "calls -- only call tools. Write your final reply only after all tools have returned.\n\n"
    "Specialist topics available: diving, hiking, skiing, cycling, surfing, climbing, sailing, "
    "wildlife_safari."
)


async def run_probe(temperature: float) -> dict[str, Any]:
    RECEIVED.clear()
    model = get_llm_by_model(settings.router_model, temperature=temperature, max_tokens=2000)
    agent = create_agent(
        model=model,
        tools=[extract_trip_fields, search_tiles, get_specialist_advice, get_local_intel],
        system_prompt=SYSTEM_PROMPT,
        name="spike_planner",
    )

    user = "plan a 7-day Bali diving trip from London, 2 adults"

    tool_call_batches: list[list[str]] = []  # tool names grouped per model turn
    prose_on_tool_turn = False
    terminal_tokens: list[str] = []

    async for mode, payload in agent.astream(
        {"messages": [HumanMessage(content=user)]},
        stream_mode=["updates", "messages"],
    ):
        if mode == "updates":
            model_update = payload.get("model") if isinstance(payload, dict) else None
            if model_update and isinstance(model_update, dict):
                for msg in model_update.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        tool_call_batches.append([tc["name"] for tc in msg.tool_calls])
        elif mode == "messages":
            chunk, _meta = payload
            if isinstance(chunk, AIMessageChunk):
                has_tool = bool(chunk.tool_call_chunks)
                has_text = (
                    bool(chunk.content) and isinstance(chunk.content, str) and chunk.content.strip()
                )
                if has_text and has_tool:
                    prose_on_tool_turn = True
                elif has_text and not has_tool:
                    terminal_tokens.append(chunk.content)

    max_batch = max((len(b) for b in tool_call_batches), default=0)
    fetch_got_dest = (
        RECEIVED.get("search_tiles", {}).get("destination", "").lower().startswith("bali")
        or any(
            v.get("destination", "").lower().startswith("bali")
            for v in RECEIVED.get("get_specialist_advice", {}).values()
        )
        or RECEIVED.get("get_local_intel", {}).get("destination", "").lower().startswith("bali")
    )

    return {
        "temperature": temperature,
        "tool_call_batches": tool_call_batches,
        "max_parallel_in_one_turn": max_batch,
        "prose_on_tool_turn": prose_on_tool_turn,
        "terminal_text_len": len("".join(terminal_tokens)),
        "received": dict(RECEIVED),
        "fetch_got_destination": fetch_got_dest,
    }


async def main() -> None:
    if not os.environ.get("GOOGLE_API_KEY") and not getattr(settings, "google_api_key", None):
        print("SKIP: no GOOGLE_API_KEY")
        return

    print(f"Model under test: {settings.router_model}\n")
    for temp in (0.0, 0.4):
        r = await run_probe(temp)
        print(f"--- temperature={temp} ---")
        print(f"  tool-call batches (per model turn): {r['tool_call_batches']}")
        print(f"  MAX parallel tool calls in one turn: {r['max_parallel_in_one_turn']}")
        print(f"  prose emitted ON a tool-calling turn: {r['prose_on_tool_turn']}")
        print(f"  terminal reply text length: {r['terminal_text_len']}")
        print(f"  fetch tools received Bali destination: {r['fetch_got_destination']}")
        print(f"  received args: {r['received']}")
        verdict_parallel = "PASS" if r["max_parallel_in_one_turn"] >= 2 else "FAIL"
        verdict_tokens = "PASS" if not r["prose_on_tool_turn"] else "FAIL"
        verdict_data = "PASS" if r["fetch_got_destination"] else "FAIL"
        print(
            f"  GATE: parallel={verdict_parallel}  clean-tokens={verdict_tokens}  "
            f"args-data={verdict_data}\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
