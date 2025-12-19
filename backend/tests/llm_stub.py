from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def _extract_between(prompt: str, start_marker: str, end_marker: str) -> str:
    start = prompt.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    end = prompt.find(end_marker, start)
    if end == -1:
        return prompt[start:].strip()
    return prompt[start:end].strip()


def _safe_json_loads(text: str) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _router_response_from_prompt(prompt: str) -> Dict[str, Any]:
    parsed_raw = _extract_between(prompt, "PARSED_INPUTS:", "USER_INTENT_HINT:")
    parsed = _safe_json_loads(parsed_raw)

    topic = parsed.get("strategy_hint")
    cats = parsed.get("category_activation") or []
    if isinstance(cats, str):
        cats = [cats]

    if topic:
        return {
            "intent": "strategy",
            "topic": topic,
            "user_intent": "detailed_planner",
            "confidence": 0.9,
            "notes": "strategy",
        }

    if "flights" in cats:
        return {
            "intent": "flights",
            "topic": None,
            "user_intent": "quick_booking" if parsed.get("_quick") else "detailed_planner",
            "confidence": 0.9,
            "notes": "flights",
        }
    if "hotels" in cats:
        return {
            "intent": "hotels",
            "topic": None,
            "user_intent": "detailed_planner",
            "confidence": 0.9,
            "notes": "hotels",
        }
    if "transport" in cats:
        return {
            "intent": "transport",
            "topic": None,
            "user_intent": "detailed_planner",
            "confidence": 0.9,
            "notes": "transport",
        }
    if "activities" in cats:
        return {
            "intent": "activities",
            "topic": None,
            "user_intent": "detailed_planner",
            "confidence": 0.9,
            "notes": "activities",
        }

    return {
        "intent": "required_fields",
        "topic": None,
        "user_intent": "detailed_planner",
        "confidence": 0.9,
        "notes": "required",
    }


def _infer_activity_categories(user_message: str) -> list[str]:
    msg = (user_message or "").lower()
    cats: list[str] = []
    if any(k in msg for k in ["food tour", "food", "sushi", "tasting", "cooking"]):
        cats.append("food")
    if any(k in msg for k in ["museum", "temple", "shrines", "culture", "history"]):
        cats.append("culture")
    if any(k in msg for k in ["hike", "hiking", "trail"]):
        cats.append("hiking")
    return cats


def llm_json_for_prompt(
    *,
    prompt: str,
    user_message: Optional[str],
) -> Dict[str, Any]:
    """Return a deterministic JSON payload matching the prompt type.

    This is a test stub for app.plan_graph.call_llm_with_timeout.
    """

    # Check for GENERATE_PLAN_NOW trigger in user_message or prompt
    # This takes priority over other handlers
    if (user_message or "").strip().upper() == "GENERATE_PLAN_NOW":
        return {
            "assistant_message": "Great - here are a couple of trip options.",
            "trip_inputs": {},
            "ready_to_generate": True,
            "branches": [
                {
                    "label": "Option A",
                    "description": "Balanced itinerary",
                    "destinations": [],
                    "tiles": {"stays": [], "flights": [], "activities": []},
                },
                {
                    "label": "Option B",
                    "description": "More relaxed pace",
                    "destinations": [],
                    "tiles": {"stays": [], "flights": [], "activities": []},
                },
            ],
            "suggested_responses": [],
        }

    # Router
    if "Role: Intent router" in prompt or "Intent router" in prompt:
        return _router_response_from_prompt(prompt)

    # Response polish
    if "polished_message" in prompt and "response_polish" in prompt:
        original = _extract_between(prompt, "ASSISTANT_MESSAGE:", "")
        return {"polished_message": original.strip() or "(polished)"}

    # Specialists
    # Detect flights specialist prompt (two possible formats)
    if (
        "SCOPE: FLIGHT PREFERENCES ONLY" in prompt
        or "Role: Travel agent handling FLIGHT preferences" in prompt
    ):
        # Get user text from either user_message param or extract from prompt
        text_to_search = user_message or ""
        if not text_to_search:
            # Extract from prompt - look for USER_MESSAGE section
            user_text_match = re.search(r'USER_MESSAGE:\s*"?([^"\n]+)', prompt)
            if user_text_match:
                text_to_search = user_text_match.group(1)
            else:
                # Try USER: pattern
                user_text_match = re.search(r"USER:\s*(.+?)(?:\n|$)", prompt)
                if user_text_match:
                    text_to_search = user_text_match.group(1)

        direct_only = bool(re.search(r"\b(direct|nonstop|no layovers)\b", text_to_search, re.I))
        round_trip = None
        if re.search(r"\b(one[- ]?way)\b", text_to_search, re.I):
            round_trip = False
        elif re.search(r"\b(round[- ]?trip|return)\b", text_to_search, re.I):
            round_trip = True

        cabin = None
        if re.search(r"\bbusiness\b", text_to_search, re.I):
            cabin = "business"
        elif re.search(r"\bfirst\b", text_to_search, re.I):
            cabin = "first"
        elif re.search(r"\bpremium\s+economy\b|\beconomy\+\b", text_to_search, re.I):
            cabin = "premium_economy"
        elif re.search(r"\beconomy\b|\bcoach\b", text_to_search, re.I):
            cabin = "economy"

        flight_settings: Dict[str, Any] = {}
        if round_trip is not None:
            flight_settings["round_trip"] = round_trip
        if direct_only:
            flight_settings["direct_only"] = True
        if cabin:
            flight_settings["cabin_class"] = cabin

        assistant = "✈️ Flights noted. Any cabin class or direct preference?"
        if flight_settings:
            assistant = "✈️ Got it—updated your flight preferences."

        return {
            "assistant_message": assistant,
            "trip_inputs": {
                "booking_types": {"flights": True},
                "flight_settings": flight_settings,
            },
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Economy is fine", "Business class", "Direct flights only"],
        }

    if "Role: Experienced travel agent helping plan trips" in prompt:
        # Used for both normal required_fields and for generation.
        if (user_message or "").strip().upper() == "GENERATE_PLAN_NOW":
            # Minimal branches, no tiles.
            return {
                "assistant_message": "✓ Great—here are a couple of trip options.",
                "trip_inputs": {},
                "ready_to_generate": True,
                "branches": [
                    {
                        "label": "Option A",
                        "description": "Balanced itinerary",
                        "destinations": [],
                        "tiles": {"stays": [], "flights": [], "activities": []},
                    },
                    {
                        "label": "Option B",
                        "description": "More relaxed pace",
                        "destinations": [],
                        "tiles": {"stays": [], "flights": [], "activities": []},
                    },
                ],
                "suggested_responses": [],
            }

        # Parse STATE from prompt to check what's already set
        state_raw = _extract_between(prompt, "STATE:", "PARSED_INPUTS:")
        state = _safe_json_loads(state_raw)
        has_destinations = bool(state.get("destinations"))
        has_origin = bool(state.get("origin"))
        has_start_date = bool(state.get("start_date"))

        iso_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", user_message or "")
        if not iso_dates:
            iso_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", prompt)

        trip_inputs: Dict[str, Any] = {}
        if len(iso_dates) >= 2:
            trip_inputs["start_date"] = iso_dates[0]
            trip_inputs["end_date"] = iso_dates[1]
            has_start_date = True
        elif len(iso_dates) == 1:
            trip_inputs["start_date"] = iso_dates[0]
            has_start_date = True

        # Check if origin is in the user message (e.g., "From Sydney")
        origin_match = re.search(r"\bfrom\s+([A-Z][a-zA-Z\s]+)", user_message or "", re.I)
        if origin_match:
            has_origin = True

        # Determine what to ask for based on what's missing
        if has_destinations and has_origin and has_start_date:
            return {
                "assistant_message": "You're all set! Ready to see options?",
                "trip_inputs": trip_inputs,
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Show me options", "Add more details"],
            }

        if has_destinations and has_origin and not has_start_date:
            dest_name = state.get("destinations", ["your destination"])[0]
            return {
                "assistant_message": f"Great—when are you planning to visit {dest_name}?",
                "trip_inputs": trip_inputs,
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Next month", "December 15-22", "Flexible dates"],
                "question_target": "dates",
            }

        if has_destinations and not has_origin:
            return {
                "assistant_message": "Where will you be flying from?",
                "trip_inputs": trip_inputs,
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["From London", "From New York", "From Sydney"],
                "question_target": "origin",
            }

        if trip_inputs:
            return {
                "assistant_message": (
                    "Got it — I’ve noted your dates. " "Anything else you want to optimize for?"
                ),
                "trip_inputs": trip_inputs,
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Budget", "Relaxed pace", "Best value"],
            }

        return {
            "assistant_message": "Where are you looking to travel, and when?",
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["I have dates", "I have a destination"],
        }

    if "SCOPE: HIKING STRATEGY ONLY" in prompt:
        # Detect Stage 2 expansion request
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        if is_stage2:
            return {
                "assistant_message": (
                    "## Complete Hiking Itinerary\n\n"
                    "**Day 1 - Arrival & Acclimatization**\n"
                    "- Arrive and settle in\n- Light 3km warm-up hike\n- Gear check\n\n"
                    "**Day 2 - Main Trail**\n"
                    "- 12km loop trail with 600m elevation\n- Pack lunch at viewpoint\n\n"
                    "**Day 3 - Summit Day**\n"
                    "- Early start, 8km to summit\n- Return via alternate route"
                ),
                "trip_inputs": {},
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Adjust difficulty", "Add rest day", "Proceed with plan"],
                "strategy_settings": {
                    "fitness_level": "moderate",
                    "trail_type": "loop",
                    "daily_distance_km": 12,
                    "elevation_gain_m": 600,
                    "notes": "full itinerary with acclimatization",
                },
                "stage": stage,
            }

        return {
            "assistant_message": (
                "Here’s a safe hiking approach: choose 1–2 core trails, plan a rest day, "
                "and keep a conservative mileage target.\n\n"
                "Trail essentials:\n- **Water**: 2L/person\n- **Footwear**: boots\n"
                "- **Weather**: layers + rain shell"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Max 10 km days", "Avoid steep climbs"],
            "strategy_settings": {
                "fitness_level": "moderate",
                "trail_type": "loop",
                "daily_distance_km": 10,
                "elevation_gain_m": 500,
                "notes": "build in buffers",
            },
            "stage": stage,
        }

    if "SCOPE: DIVING STRATEGY ONLY" in prompt:
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        if is_stage2:
            return {
                "assistant_message": (
                    "## Complete Diving Itinerary\n\n"
                    "**Day 1 - Checkout Dive**\n"
                    "- 2 easy dives, max 18m\n- Equipment familiarization\n\n"
                    "**Day 2 - Advanced Sites**\n"
                    "- Morning: wall dive to 25m\n- Afternoon: drift dive\n\n"
                    "**Day 3 - Highlight Dive**\n"
                    "- Famous wreck or reef site"
                ),
                "trip_inputs": {},
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["More shore dives", "Add night dive", "Proceed with plan"],
                "strategy_settings": {
                    "certification_level": "open_water",
                    "max_depth_m": 25,
                    "dive_type": "boat",
                    "equipment_rental": True,
                    "notes": "full itinerary with progression",
                },
                "stage": stage,
            }

        return {
            "assistant_message": (
                "Let's plan your dive trip safely. What's your certification level?\n\n"
                "Key considerations:\n- **Surface intervals**: min 1hr between dives\n"
                "- **Depth limits**: based on certification\n- **Equipment**: rental or own?"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Open Water certified", "Advanced certified", "Discover Scuba"],
            "strategy_settings": {
                "certification_level": "open_water",
                "max_depth_m": 18,
                "dive_type": "boat",
                "equipment_rental": True,
                "notes": "confirm certification",
            },
            "stage": stage,
        }

    if "SCOPE: SKIING STRATEGY ONLY" in prompt:
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        if is_stage2:
            return {
                "assistant_message": (
                    "## Complete Ski Itinerary\n\n"
                    "**Day 1 - Warm Up**\n"
                    "- Morning: groomed blues\n- Afternoon: explore the mountain\n\n"
                    "**Day 2 - Full Day**\n"
                    "- Challenge yourself on reds/blacks\n- Lunch at mountain restaurant\n\n"
                    "**Day 3 - Final Runs**\n"
                    "- Morning skiing\n- Early afternoon departure"
                ),
                "trip_inputs": {},
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Add lessons", "More off-piste", "Proceed with plan"],
                "strategy_settings": {
                    "skill_level": "intermediate",
                    "terrain_preference": "groomed",
                    "lift_pass_type": "full_area",
                    "equipment_rental": True,
                    "notes": "full itinerary with progression",
                },
                "stage": stage,
            }

        return {
            "assistant_message": (
                "Let's plan your ski trip! What's your skiing ability?\n\n"
                "Consider:\n- **Terrain**: greens/blues/blacks\n"
                "- **Lessons**: available at most resorts\n- **Equipment**: rent or bring?"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Beginner", "Intermediate", "Advanced"],
            "strategy_settings": {
                "skill_level": "intermediate",
                "terrain_preference": "groomed",
                "lift_pass_type": "full_area",
                "equipment_rental": True,
                "notes": "confirm skill level",
            },
            "stage": stage,
        }

    if "SCOPE: CYCLING STRATEGY ONLY" in prompt:
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        if is_stage2:
            return {
                "assistant_message": (
                    "## Complete Cycling Itinerary\n\n"
                    "**Day 1 - Easy Start**\n"
                    "- 40km flat route along the coast\n- Cafe stops included\n\n"
                    "**Day 2 - Main Challenge**\n"
                    "- 70km with 800m climbing\n- Scenic mountain pass\n\n"
                    "**Day 3 - Recovery Ride**\n"
                    "- 30km loop, mostly flat"
                ),
                "trip_inputs": {},
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Reduce distance", "Add rest day", "Proceed with plan"],
                "strategy_settings": {
                    "fitness_level": "intermediate",
                    "route_type": "mixed",
                    "daily_distance_km": 50,
                    "bike_type": "road",
                    "notes": "full itinerary with build-up",
                },
                "stage": stage,
            }

        return {
            "assistant_message": (
                "Let's plan your cycling adventure! What's your fitness level?\n\n"
                "Key factors:\n- **Distance**: daily km target\n"
                "- **Terrain**: flat, hilly, or mixed\n- **Bike**: road, gravel, or hybrid?"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["30-50km days", "50-80km days", "80+ km days"],
            "strategy_settings": {
                "fitness_level": "intermediate",
                "route_type": "mixed",
                "daily_distance_km": 50,
                "bike_type": "road",
                "notes": "confirm fitness level",
            },
            "stage": stage,
        }

    if "SCOPE: BOATING STRATEGY ONLY" in prompt:
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        if is_stage2:
            return {
                "assistant_message": (
                    "## Complete Boating Itinerary\n\n"
                    "**Day 1 - Departure**\n"
                    "- Morning: boat briefing and provisioning\n- Sail to first anchorage\n\n"
                    "**Day 2 - Island Hopping**\n"
                    "- Visit 2-3 islands\n- Swimming and snorkeling stops\n\n"
                    "**Day 3 - Return**\n"
                    "- Morning sail back\n- Boat handover by noon"
                ),
                "trip_inputs": {},
                "ready_to_generate": False,
                "branches": [],
                "suggested_responses": ["Longer trip", "Add water sports", "Proceed with plan"],
                "strategy_settings": {
                    "experience_level": "intermediate",
                    "vessel_type": "sailing_yacht",
                    "trip_duration_days": 3,
                    "crew_required": False,
                    "notes": "full itinerary with island hopping",
                },
                "stage": stage,
            }

        return {
            "assistant_message": (
                "Let's plan your boating trip! What's your sailing experience?\n\n"
                "Options:\n- **Bareboat**: you captain (license required)\n"
                "- **Skippered**: professional captain included\n- **Crewed**: full crew with chef"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Bareboat", "Skippered", "Fully crewed"],
            "strategy_settings": {
                "experience_level": "beginner",
                "vessel_type": "sailing_yacht",
                "trip_duration_days": 3,
                "crew_required": True,
                "notes": "confirm experience level",
            },
            "stage": stage,
        }

    if "SCOPE:" in prompt and "STRATEGY" in prompt:
        # Fallback for any other strategy prompt not matched above
        user_msg_lower = (user_message or "").lower()
        is_stage2 = any(
            trigger in user_msg_lower
            for trigger in ["expand", "show details", "full itinerary", "more details", "elaborate"]
        )
        stage = "stage2" if is_stage2 else "stage1"

        return {
            "assistant_message": (
                "Let's plan this in a safe, step-by-step way. " "What's your skill level?"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Beginner", "Intermediate", "Advanced"],
            "strategy_settings": {"notes": "confirm skill level"},
            "stage": stage,
        }

    # Match specialists by the explicit SCOPE line to avoid false positives from
    # JSON keys inside PARSED_INPUTS (e.g. "activity_settings_delta").
    if "SCOPE: CORRECTION" in prompt.upper():
        return {
            "assistant_message": (
                "⚠️ **That won’t quite work** because the plan has a conflict. "
                "We could **adjust the destination** or **adjust the activity focus**. "
                "Which should I apply?"
            ),
            "trip_inputs": {},
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Adjust the destination", "Adjust the activities"],
        }

    if "SCOPE: HOTEL PREFERENCES ONLY" in prompt.upper():
        parsed_raw = _extract_between(prompt, "PARSED_INPUTS:", "==============================")
        parsed = _safe_json_loads(parsed_raw)
        hotel_delta = parsed.get("hotel_settings_delta") or {}
        return {
            "assistant_message": "🏨 Hotel preferences noted. Any must-have neighborhood?",
            "trip_inputs": {
                "booking_types": {"hotels": True},
                "hotel_settings": hotel_delta,
            },
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Central location", "Quiet area"],
        }

    if (
        "SCOPE: TRANSPORT PREFERENCES ONLY" in prompt.upper()
        or "GROUND TRANSPORT preferences" in prompt
    ):
        msg = (user_message or "").lower()
        transport: Dict[str, Any] = {}
        if any(k in msg for k in ["rent a car", "car rental", "drive", "driving"]):
            transport["car"] = True
        if "train" in msg:
            transport["train"] = True
        if "bus" in msg:
            transport["bus"] = True

        if not transport:
            transport = {"car": True}

        return {
            "assistant_message": (
                "🚆 Transport preferences noted. " "Any must-haves (direct, scenic, budget)?"
            ),
            "trip_inputs": {
                "booking_types": {"ground_transport": True},
                "transport_settings": transport,
            },
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Train is fine", "Rent a car", "Prefer buses"],
        }

    if "SCOPE: ACTIVITY PREFERENCES ONLY" in prompt.upper():
        cats = _infer_activity_categories(user_message or "")
        return {
            "assistant_message": "🎭 Activities noted. Any pace preference (relaxed vs packed)?",
            "trip_inputs": {
                "booking_types": {"activities": True},
                "activity_settings": {"categories": cats},
            },
            "ready_to_generate": False,
            "branches": [],
            "suggested_responses": ["Relaxed pace", "Packed schedule"],
        }

    # Extractor prompt - extract trip details from user message
    if (
        "EXTRACTION NODE" in prompt
        or "LIGHT EXTRACTION NODE" in prompt
        or "Role: Extract ALL trip planning details" in prompt
        or "Role: Quick extraction of core trip details only" in prompt
    ):
        # For extractor prompts, user_message may not be passed separately -
        # it's embedded in the prompt template. Extract it from the prompt if needed.
        effective_user_message = user_message
        if not effective_user_message:
            # Try to extract from LIGHT prompt format: User message: "..."
            match = re.search(r'User message:\s*"([^"]+)"', prompt)
            if match:
                effective_user_message = match.group(1)
            else:
                # Try to extract from FULL prompt format: USER_TEXT: ...
                match = re.search(r"USER_TEXT:\s*(.+?)(?:\n|$)", prompt)
                if match:
                    effective_user_message = match.group(1).strip()

        msg = (effective_user_message or "").lower()
        result: Dict[str, Any] = {
            "confidence": 0.9,
            "destinations_delta": None,
            "origin_delta": None,
            "start_date_hint": None,
            "end_date_hint": None,
            "duration_days": None,
            "adults_delta": None,
            "children_delta": None,
            "budget_delta": None,
            "currency_delta": None,
            "notes_delta": None,
            "strategy_hint": None,
            "category_activation": [],
            "multi_city_intent_delta": None,
        }

        # Extract destinations
        dest_patterns = [
            # Pattern for "to X" where X is a proper noun (capitalized) place name
            r"\bto\s+the\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b",  # "to the Swiss Alps"
            r"\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b",  # "to Paris", "to New York"
            r"\bvisit\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b",  # "visit Tokyo"
            r"\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b",  # "in Rome"
        ]
        for pattern in dest_patterns:
            match = re.search(pattern, effective_user_message or "")
            if match:
                dest = match.group(1).strip()
                if dest.lower() not in ["i", "a", "the", "my", "we", "from", "for", "and"]:
                    result["destinations_delta"] = [dest]
                    break

        # Extract origin
        origin_match = re.search(
            r"\bfrom\s+([A-Z][a-zA-Z\s]+?)(?:\s+to|\s*$|[,.])", effective_user_message or "", re.I
        )
        if origin_match:
            result["origin_delta"] = origin_match.group(1).strip()

        # Extract dates (ISO format)
        iso_dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", effective_user_message or "")
        if len(iso_dates) >= 2:
            result["start_date_hint"] = iso_dates[0]
            result["end_date_hint"] = iso_dates[1]
        elif len(iso_dates) == 1:
            result["start_date_hint"] = iso_dates[0]

        # Extract travelers
        adults_match = re.search(r"(\d+)\s*adults?", msg)
        if adults_match:
            result["adults_delta"] = int(adults_match.group(1))

        children_match = re.search(r"(\d+)\s*(?:kids?|children)", msg)
        if children_match:
            result["children_delta"] = int(children_match.group(1))

        # Detect strategy hints (use word boundaries to avoid false matches)
        if any(k in msg for k in ["hike", "hiking", "trek"]):
            result["strategy_hint"] = "hiking"
        elif any(k in msg for k in ["dive", "diving", "scuba", "snorkel"]):
            result["strategy_hint"] = "diving"
        # Check boating BEFORE skiing - "skippered" contains "ski" but is a boating term
        elif any(k in msg for k in ["boat", "sail", "yacht", "cruise", "skippered", "bareboat"]):
            result["strategy_hint"] = "boating"
        elif re.search(r"\bski(ing|s)?\b|\bsnowboard", msg):
            # Use word boundary to avoid matching "skippered"
            result["strategy_hint"] = "skiing"
        elif any(k in msg for k in ["bike", "cycling", "biking"]):
            result["strategy_hint"] = "cycling"

        # Detect category activations
        if any(k in msg for k in ["flight", "fly", "flying"]):
            result["category_activation"].append("flights")
        if any(k in msg for k in ["hotel", "stay", "accommodation"]):
            result["category_activation"].append("hotels")
        if any(k in msg for k in ["car", "train", "bus", "transport"]):
            result["category_activation"].append("transport")
        if any(k in msg for k in ["activity", "activities", "tour", "museum"]):
            result["category_activation"].append("activities")

        # Detect multi-city intent
        # Phrases like "all together", "one trip", "combined", etc. indicate multi_city
        if any(
            phrase in msg
            for phrase in [
                "all together",
                "one trip",
                "combined trip",
                "multi-city",
                "multicity",
                "connect them",
                "same trip",
                "single trip",
            ]
        ):
            result["multi_city_intent_delta"] = "multi_city"

        # Extract hotel settings (min_stars and amenities)
        hotel_settings: Dict[str, Any] = {}
        # Min stars: look for patterns like "4-star", "4 star", "5-star hotel"
        stars_match = re.search(r"(\d+)\s*-?\s*star", msg)
        if stars_match:
            hotel_settings["min_stars"] = int(stars_match.group(1))
        # Amenities: look for common hotel amenities
        amenities: list[str] = []
        if "breakfast" in msg:
            amenities.append("breakfast")
        if "gym" in msg or "fitness" in msg:
            amenities.append("gym")
        if "pool" in msg or "swimming" in msg:
            amenities.append("pool")
        if "spa" in msg:
            amenities.append("spa")
        if "wifi" in msg or "wi-fi" in msg:
            amenities.append("wifi")
        if amenities:
            hotel_settings["amenities"] = amenities
        if hotel_settings:
            result["hotel_settings_delta"] = hotel_settings

        # Extract flight settings (round_trip, cabin_class, direct_only)
        flight_settings: Dict[str, Any] = {}
        # One-way flights
        if "one-way" in msg or "one way" in msg or "oneway" in msg:
            flight_settings["round_trip"] = False
        # Cabin class
        if "business" in msg:
            flight_settings["cabin_class"] = "business"
        elif "first class" in msg:
            flight_settings["cabin_class"] = "first"
        # Direct/nonstop
        if "direct" in msg or "nonstop" in msg or "non-stop" in msg:
            flight_settings["direct_only"] = True
        if flight_settings:
            result["flight_settings_delta"] = flight_settings

        return result

    # Condense prompt - shorten a long message
    if "Message condenser" in prompt or "condense a message" in prompt:
        # Extract the original message and return a shortened version
        original = _extract_between(prompt, "Original message to condense:", "Target length:")
        if not original:
            original = _extract_between(prompt, "message}", "{target_length")
        # Return a condensed version (just take first portion)
        condensed = original.strip()[:200] + "..." if len(original) > 200 else original.strip()
        return {"condensed_message": condensed}

    # Default safe response
    return {
        "assistant_message": "Where would you like to go?",
        "trip_inputs": {},
        "ready_to_generate": False,
        "branches": [],
        "suggested_responses": [],
    }
