"""
Scenario generator for LLM-driven conversation testing.

Uses GPT-4o to generate diverse, realistic conversation scenarios
with user profiles, goals, constraints, and multi-turn user messages.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from openai import AsyncOpenAI

# Import E2E model constant
try:
    from tests.e2e.conftest import E2E_MODEL
except ImportError:
    E2E_MODEL = "gpt-4o"  # Fallback if running standalone

# Difficulty levels for scenario generation
DifficultyLevel = Literal["easy", "medium", "hard", "edge_case"]

# Scenario categories for comprehensive coverage
ScenarioCategory = Literal[
    "quick_booking",  # Same-day, last-minute, weekend trips
    "business_travel",  # Day trips, conferences, corporate travel
    "extended_vacation",  # Multi-week trips, backpacking
    "family_trip",  # Family-friendly, multi-generational
    "group_complex",  # Destination weddings, corporate retreats
    "accessibility",  # Wheelchair, dietary, medical needs
    "budget_extreme",  # Ultra-budget or ultra-luxury
    "geographic_diverse",  # Africa, South America, Middle East, etc.
    "cancellation",  # Changes, cancellations, rebooking
    "edge_case",  # Visa, passport, advisories, peak pricing
]

# Persona types for diverse user profiles
PersonaType = Literal[
    "budget_backpacker",
    "luxury_traveler",
    "family_vacation",
    "business_trip",
    "adventure_seeker",
    "honeymoon_couple",
    "solo_explorer",
    "group_friends",
]


@dataclass
class UserProfile:
    """Represents a synthetic user's characteristics."""

    persona: PersonaType
    experience_level: Literal["novice", "intermediate", "expert"]
    communication_style: Literal["casual", "formal", "terse", "verbose"]
    decision_making: Literal["decisive", "indecisive", "detail_oriented"]

    def to_dict(self) -> Dict[str, str]:
        return {
            "persona": self.persona,
            "experience_level": self.experience_level,
            "communication_style": self.communication_style,
            "decision_making": self.decision_making,
        }


@dataclass
class ScenarioConstraints:
    """Travel constraints for the scenario."""

    budget: Optional[str] = None
    dates: Optional[str] = None
    preferences: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)
    party_size: Optional[str] = None
    special_requirements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget": self.budget,
            "dates": self.dates,
            "preferences": self.preferences,
            "avoid": self.avoid,
            "party_size": self.party_size,
            "special_requirements": self.special_requirements,
        }


@dataclass
class DifficultySettings:
    """Settings that control scenario difficulty."""

    level: DifficultyLevel
    ambiguity_level: Literal["none", "low", "medium", "high"]
    missing_inputs: List[str] = field(default_factory=list)
    edge_cases: List[str] = field(default_factory=list)
    conflicting_constraints: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "ambiguity_level": self.ambiguity_level,
            "missing_inputs": self.missing_inputs,
            "edge_cases": self.edge_cases,
            "conflicting_constraints": self.conflicting_constraints,
        }


@dataclass
class ConversationTurn:
    """A single user message in the conversation."""

    turn_number: int
    user_message: str
    intent_hint: Optional[str] = None  # What the user is trying to accomplish

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn_number,
            "user_message": self.user_message,
            "intent_hint": self.intent_hint,
        }


@dataclass
class ConversationScenario:
    """A complete conversation scenario for testing."""

    scenario_id: str
    user_profile: UserProfile
    goal: str
    constraints: ScenarioConstraints
    difficulty: DifficultySettings
    turns: List[ConversationTurn]
    expected_outcomes: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "user_profile": self.user_profile.to_dict(),
            "goal": self.goal,
            "constraints": self.constraints.to_dict(),
            "difficulty": self.difficulty.to_dict(),
            "turns": [t.to_dict() for t in self.turns],
            "expected_outcomes": self.expected_outcomes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationScenario":
        """Create a scenario from a dictionary."""
        return cls(
            scenario_id=data["scenario_id"],
            user_profile=UserProfile(**data["user_profile"]),
            goal=data["goal"],
            constraints=ScenarioConstraints(**data["constraints"]),
            difficulty=DifficultySettings(**data["difficulty"]),
            turns=[ConversationTurn(**t) for t in data["turns"]],
            expected_outcomes=data.get("expected_outcomes", {}),
            metadata=data.get("metadata", {}),
        )


# System prompt for scenario generation
SCENARIO_GENERATOR_PROMPT = """You are a test scenario generator for a travel planning AI assistant.

Your job is to create realistic, diverse conversation scenarios that test
the travel planning system thoroughly.

The travel planning system helps users:
- Plan trips with destinations, dates, and travelers
- Book flights, hotels, and activities
- Handle special requirements (accessibility, dietary, etc.)
- Provide advice on activities like hiking, diving, skiing, boating

## SCENARIO CATEGORIES TO COVER

### Quick Bookings (urgent, time-sensitive)
- Same-day or next-day trips ("I need a flight to Chicago tonight")
- Last-minute weekend getaways ("Spontaneous trip this Friday")
- Red-eye flights, tight connections
- "I must be back by Monday morning"

### Business Travel
- Day trips for meetings ("Quick trip to NYC for a meeting tomorrow")
- Conference attendance with specific hotel requirements
- Multi-city work tours with per diem constraints
- Corporate travel policies and expense limits

### Extended Vacations
- Multi-week backpacking trips
- Round-the-world itineraries
- Gap year planning
- Sabbatical travel

### Family & Group Complexity
- Multi-generational trips (grandparents + parents + kids)
- Destination weddings with guest coordination
- Corporate retreats with team-building activities
- Friend group trips with budget disparities

### Accessibility & Special Needs
- Wheelchair accessible accommodations
- Dietary restrictions (allergies, kosher, halal, vegan)
- Traveling with medical equipment
- Traveling with pets/service animals
- Elderly travelers with mobility concerns

### Budget Extremes
- Ultra-budget (<$500 total, hostels, budget airlines)
- Ultra-luxury (>$50k, first class, 5-star only)
- Specific price constraints ("exactly $2000")

### Geographic Diversity
- Africa safaris
- South America adventures
- Middle East cultural tours
- Australia/New Zealand
- Domestic US road trips
- Lesser-known destinations

### Cancellations & Changes
- "I need to change my dates"
- "What's the cancellation policy?"
- "My flight was cancelled, help!"
- Rebooking scenarios

### Edge Cases
- Visa and passport requirements
- Travel advisories and warnings
- Peak season pricing complaints
- Currency conversion questions
- Timezone confusion
- Open-jaw flights
- Stopovers and layovers

## DIFFICULTY LEVELS

1. **Easy**: Simple straightforward trips with clear requirements
2. **Medium**: Multi-destination or complex requirements
3. **Hard**: Ambiguous requests needing clarification, conflicting constraints
4. **Edge Case**: Unusual situations testing error handling and robustness

## GENERATION GUIDELINES

For each scenario, generate 6-12 realistic user messages that simulate a natural conversation flow.
The user should gradually reveal information, ask questions, change their mind
occasionally, and behave like a real person.

IMPORTANT:
- Keep temperature > 0 to ensure diverse outputs
- Vary the communication style based on the persona
- Include realistic typos or informal language for casual personas
- For "hard" scenarios, make the user provide incomplete or ambiguous information initially
- Include at least one scenario per session that tests time pressure ("I need this booked now")
- Include scenarios with specific constraint conflicts that need resolution
"""


SCENARIO_GENERATION_TEMPLATE = """Generate a conversation scenario with the following parameters:

Persona Type: {persona_type}
Difficulty Level: {difficulty_level}
Target Turns: {num_turns}
Focus Area: {focus_area}

The scenario should test: {test_focus}

Return a JSON object with this exact structure:
{{
    "scenario_id": "unique-uuid-here",
    "user_profile": {{
        "persona": "{persona_type}",
        "experience_level": "novice|intermediate|expert",
        "communication_style": "casual|formal|terse|verbose",
        "decision_making": "decisive|indecisive|detail_oriented"
    }},
    "goal": "Clear description of what the user wants to achieve",
    "constraints": {{
        "budget": "e.g., $2000 or null",
        "dates": "e.g., flexible March 2025 or specific dates or null",
        "preferences": ["list", "of", "preferences"],
        "avoid": ["things", "to", "avoid"],
        "party_size": "e.g., 2 adults, 1 child or null",
        "special_requirements": ["accessibility", "dietary", etc]
    }},
    "difficulty": {{
        "level": "{difficulty_level}",
        "ambiguity_level": "none|low|medium|high",
        "missing_inputs": ["dates", "budget", etc],
        "edge_cases": ["timezone", "currency", etc],
        "conflicting_constraints": true|false
    }},
    "turns": [
        {{"turn": 1, "user_message": "First message from user", "intent_hint": "Initial request"}},
        {{"turn": 2, "user_message": "Follow-up message", "intent_hint": "Providing details"}}
    ],
    "expected_outcomes": {{
        "should_extract_destinations": true,
        "should_ask_clarification": false,
        "expected_intent_sequence": ["required_fields", "flights", "hotels"]
    }},
    "metadata": {{
        "test_category": "multi_city|simple_trip|edge_case|strategy",
        "generated_at": "ISO timestamp"
    }}
}}

Generate only the JSON, no additional text.
"""


class ScenarioGenerator:
    """Generates conversation scenarios using GPT-4o."""

    def __init__(
        self,
        model: str = E2E_MODEL,
        temperature: float = 0.8,  # Higher for diversity
        api_key: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        self._client: Optional[AsyncOpenAI] = None
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def generate_scenario(
        self,
        persona_type: PersonaType = "solo_explorer",
        difficulty_level: DifficultyLevel = "medium",
        num_turns: int = 8,
        focus_area: str = "general trip planning",
        test_focus: str = "end-to-end conversation flow",
    ) -> ConversationScenario:
        """Generate a single conversation scenario."""

        prompt = SCENARIO_GENERATION_TEMPLATE.format(
            persona_type=persona_type,
            difficulty_level=difficulty_level,
            num_turns=num_turns,
            focus_area=focus_area,
            test_focus=test_focus,
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SCENARIO_GENERATOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from LLM")

        data = json.loads(content)

        # Ensure scenario_id is unique
        if not data.get("scenario_id") or data["scenario_id"] == "unique-uuid-here":
            data["scenario_id"] = str(uuid.uuid4())

        return ConversationScenario.from_dict(data)

    async def generate_scenario_batch(
        self,
        count: int = 5,
        difficulty_distribution: Optional[Dict[DifficultyLevel, int]] = None,
        persona_distribution: Optional[Dict[PersonaType, int]] = None,
    ) -> List[ConversationScenario]:
        """Generate multiple diverse scenarios."""

        if difficulty_distribution is None:
            difficulty_distribution = {
                "easy": count // 4,
                "medium": count // 2,
                "hard": count // 4 or 1,
                "edge_case": max(1, count // 5),
            }

        if persona_distribution is None:
            personas: List[PersonaType] = [
                "budget_backpacker",
                "luxury_traveler",
                "family_vacation",
                "business_trip",
                "adventure_seeker",
                "honeymoon_couple",
                "solo_explorer",
                "group_friends",
            ]
            persona_distribution = {p: max(1, count // len(personas)) for p in personas}

        scenarios = []

        # Generate scenarios for each difficulty level
        for difficulty, num in difficulty_distribution.items():
            for _ in range(num):
                # Pick a random persona from remaining allocation
                available_personas = [p for p, c in persona_distribution.items() if c > 0]
                if not available_personas:
                    available_personas = list(persona_distribution.keys())

                persona = available_personas[len(scenarios) % len(available_personas)]

                scenario = await self.generate_scenario(
                    persona_type=persona,
                    difficulty_level=difficulty,
                    num_turns=8 if difficulty in ("easy", "medium") else 10,
                    focus_area=self._get_focus_for_difficulty(difficulty),
                    test_focus=self._get_test_focus(difficulty),
                )
                scenarios.append(scenario)

                if len(scenarios) >= count:
                    break

            if len(scenarios) >= count:
                break

        return scenarios[:count]

    def _get_focus_for_difficulty(self, difficulty: DifficultyLevel) -> str:
        """Get appropriate focus area for difficulty level."""
        focus_map = {
            "easy": "simple single-destination trip",
            "medium": "multi-city trip with specific preferences",
            "hard": "complex trip with ambiguous requirements",
            "edge_case": "edge cases: timezone conflicts, currency, availability",
        }
        return focus_map.get(difficulty, "general trip planning")

    def _get_test_focus(self, difficulty: DifficultyLevel) -> str:
        """Get test focus description for difficulty level."""
        focus_map = {
            "easy": "basic extraction and required fields flow",
            "medium": "intent routing and specialist node handling",
            "hard": "clarification handling and ambiguity resolution",
            "edge_case": "error handling, fallbacks, and edge case robustness",
        }
        return focus_map.get(difficulty, "end-to-end conversation flow")


# Predefined scenario templates for golden replays
GOLDEN_SCENARIOS = [
    {
        "name": "simple_paris_trip",
        "description": "Straightforward 5-day Paris trip for 2 adults",
        "user_profile": {
            "persona": "honeymoon_couple",
            "experience_level": "intermediate",
            "communication_style": "casual",
            "decision_making": "decisive",
        },
        "goal": "Plan a romantic 5-day trip to Paris",
        "constraints": {
            "budget": "$5000",
            "dates": "March 15-20, 2025",
            "preferences": ["romantic restaurants", "museums", "wine tours"],
            "party_size": "2 adults",
        },
        "turns": [
            "Hi! We want to plan a romantic trip to Paris for our anniversary",
            "We're thinking March 15-20, 2025",
            "It's just the two of us, and we have about $5000 to spend",
            "We love museums and wine. Any romantic restaurant suggestions?",
            "That sounds perfect! Can you help us find flights from New York?",
            "And a nice boutique hotel in the Marais district?",
        ],
    },
    {
        "name": "complex_asia_backpacking",
        "description": "Multi-city backpacking trip with budget constraints",
        "user_profile": {
            "persona": "budget_backpacker",
            "experience_level": "novice",
            "communication_style": "casual",
            "decision_making": "indecisive",
        },
        "goal": "Plan 3-week Southeast Asia trip on a tight budget",
        "constraints": {
            "budget": "$2000",
            "dates": "flexible, sometime in summer",
            "preferences": ["beaches", "street food", "hostels"],
            "avoid": ["tourist traps"],
            "party_size": "1 adult",
        },
        "turns": [
            "hey i wanna go backpacking in asia this summer, got like 2k to spend",
            "maybe thailand? or vietnam? idk which is better",
            "somewhere with good beaches and cheap food",
            "probably 3 weeks or so, im flexible on dates",
            "wait actually could i do both countries in one trip?",
            "how do i get between them? is there a cheap way?",
            "ok lets do thailand first then vietnam. help me plan this?",
        ],
    },
    {
        "name": "family_ski_trip",
        "description": "Family ski vacation with children and accessibility needs",
        "user_profile": {
            "persona": "family_vacation",
            "experience_level": "intermediate",
            "communication_style": "formal",
            "decision_making": "detail_oriented",
        },
        "goal": "Plan a family ski trip with kid-friendly options",
        "constraints": {
            "budget": "$8000",
            "dates": "December 26 - January 2",
            "preferences": ["ski-in/ski-out", "kids lessons", "family dining"],
            "special_requirements": ["beginner slopes for kids"],
            "party_size": "2 adults, 2 children (ages 8 and 12)",
        },
        "turns": [
            "We're looking to plan a family ski trip over the holidays.",
            "December 26th through January 2nd would work best for us.",
            "There will be 4 of us - my wife and I, plus our kids aged 8 and 12.",
            "The children are beginners, so we'd need resorts with good ski schools.",
            "We'd prefer ski-in/ski-out accommodation if possible.",
            "Our budget is around $8000 for the whole trip.",
            "Would Colorado or Utah be better for families?",
            "What about après-ski activities for the kids?",
        ],
    },
    # Quick booking - last minute weekend trip
    {
        "name": "last_minute_weekend",
        "description": "Urgent last-minute weekend getaway booking",
        "user_profile": {
            "persona": "solo_explorer",
            "experience_level": "intermediate",
            "communication_style": "terse",
            "decision_making": "decisive",
        },
        "goal": "Book a spontaneous weekend trip departing tomorrow",
        "constraints": {
            "budget": "$800",
            "dates": "this Friday to Sunday",
            "preferences": ["beach", "warm weather"],
            "party_size": "1 adult",
        },
        "turns": [
            "I need to get away this weekend. Flying out tomorrow.",
            "Somewhere warm with a beach, dont care where exactly",
            "Budget is maybe 800 bucks total",
            "Just me, traveling solo",
            "What are my options for flights leaving Friday morning?",
            "That works. Can you find a hotel near the beach?",
        ],
    },
    # Business travel - day trip
    {
        "name": "business_day_trip",
        "description": "Quick business day trip for a meeting",
        "user_profile": {
            "persona": "business_trip",
            "experience_level": "expert",
            "communication_style": "formal",
            "decision_making": "decisive",
        },
        "goal": "Arrange same-day round trip for business meeting",
        "constraints": {
            "budget": "company expense account",
            "dates": "next Tuesday",
            "preferences": ["morning departure", "evening return", "aisle seat"],
            "party_size": "1 adult",
        },
        "turns": [
            "I need to fly to Chicago next Tuesday for a client meeting.",
            "It's a day trip - leave early morning, return same evening.",
            "The meeting is at 2pm downtown, so I need to land by noon.",
            "I'll need a car service from O'Hare to the Loop.",
            "Aisle seat preferred. This goes on the company card.",
            "What time does the last flight back to Boston leave?",
        ],
    },
    # Accessibility needs
    {
        "name": "wheelchair_accessible_trip",
        "description": "Trip planning with wheelchair accessibility requirements",
        "user_profile": {
            "persona": "family_vacation",
            "experience_level": "intermediate",
            "communication_style": "formal",
            "decision_making": "detail_oriented",
        },
        "goal": "Plan accessible vacation for family member using wheelchair",
        "constraints": {
            "budget": "$6000",
            "dates": "April 10-17",
            "preferences": ["museums", "accessible tours", "ground floor rooms"],
            "special_requirements": [
                "wheelchair accessible",
                "roll-in shower",
                "accessible transportation",
            ],
            "party_size": "2 adults (one wheelchair user)",
        },
        "turns": [
            "We're planning a trip to Rome and my mother uses a wheelchair.",
            "We need everything to be fully wheelchair accessible.",
            "Hotels must have roll-in showers and ground floor or elevator access.",
            "April 10-17 would work. Budget is about $6000.",
            "Are the main tourist sites in Rome accessible?",
            "We'll need accessible transportation from the airport too.",
            "What about accessible tours of the Vatican?",
        ],
    },
    # Destination wedding
    {
        "name": "destination_wedding",
        "description": "Destination wedding with guest group coordination",
        "user_profile": {
            "persona": "group_friends",
            "experience_level": "novice",
            "communication_style": "verbose",
            "decision_making": "indecisive",
        },
        "goal": "Plan destination wedding trip for wedding party",
        "constraints": {
            "budget": "$3000 per person",
            "dates": "June 15-22",
            "preferences": ["beachfront", "group activities", "wedding venue nearby"],
            "party_size": "8 adults",
        },
        "turns": [
            (
                "My best friend is getting married in Cancun "
                "and I'm organizing travel for the bridal party."
            ),
            "There are 8 of us total. We all want to stay at the same resort.",
            "The wedding is June 20th but we want to arrive a few days early.",
            "Everyone has different budgets... some are more flexible than others.",
            "Can we get a group rate on rooms? We'd need at least 4 rooms.",
            "We also need to plan the bachelorette party - maybe a boat trip?",
            "What about transportation from the airport for everyone?",
            "Some people are flying from different cities. Can you coordinate?",
        ],
    },
    # Ultra-budget trip
    {
        "name": "ultra_budget_europe",
        "description": "Extreme budget trip with strict constraints",
        "user_profile": {
            "persona": "budget_backpacker",
            "experience_level": "novice",
            "communication_style": "casual",
            "decision_making": "decisive",
        },
        "goal": "Visit Europe for 2 weeks spending under $1500 total",
        "constraints": {
            "budget": "$1500 maximum including flights",
            "dates": "flexible, summer",
            "preferences": ["hostels", "budget airlines", "free walking tours"],
            "avoid": ["expensive cities like London or Paris"],
            "party_size": "1 adult",
        },
        "turns": [
            "i want to backpack europe this summer but im broke lol",
            "like seriously my total budget is $1500 including flights",
            "is that even possible? i can rough it, hostels are fine",
            "maybe eastern europe is cheaper? idk",
            "i have like 2 weeks to travel",
            "whats the cheapest way to fly from NYC to europe?",
            "can i take buses between countries to save money?",
        ],
    },
    # Change/cancellation request
    {
        "name": "trip_change_request",
        "description": "User needs to modify existing travel plans",
        "user_profile": {
            "persona": "business_trip",
            "experience_level": "intermediate",
            "communication_style": "formal",
            "decision_making": "decisive",
        },
        "goal": "Change travel dates due to schedule conflict",
        "constraints": {
            "budget": "willing to pay change fees",
            "dates": "need to move from May 5-10 to May 12-17",
            "preferences": ["same hotel if possible"],
            "party_size": "1 adult",
        },
        "turns": [
            "I need to change my upcoming trip to Seattle.",
            "I was supposed to go May 5-10 but now I need to push it to May 12-17.",
            "My meeting got rescheduled. Can I change my flight without huge fees?",
            "I'd like to keep the same hotel if they have availability.",
            "What's the cancellation policy on my current booking?",
            "If I can't change it, can I at least get credit for future travel?",
        ],
    },
    # Multi-generational family
    {
        "name": "multigenerational_cruise",
        "description": "Three-generation family trip with diverse needs",
        "user_profile": {
            "persona": "family_vacation",
            "experience_level": "intermediate",
            "communication_style": "verbose",
            "decision_making": "detail_oriented",
        },
        "goal": "Plan family reunion trip for grandparents, parents, and kids",
        "constraints": {
            "budget": "$15000",
            "dates": "first week of August",
            "preferences": [
                "activities for all ages",
                "connecting rooms",
                "accessible for elderly",
            ],
            "special_requirements": [
                "grandpa has mobility issues",
                "kids need entertainment",
            ],
            "party_size": "2 grandparents, 2 adults, 3 children",
        },
        "turns": [
            "We're planning a big family reunion trip - three generations!",
            "It's my parents, my wife and I, and our three kids ages 5, 8, and 14.",
            "Grandpa uses a cane so we need to think about accessibility.",
            "A cruise might work well since it has activities for everyone?",
            "The kids want water slides, grandma wants the spa.",
            "We'd need connecting cabins or at least cabins close together.",
            "First week of August works for everyone's schedules.",
            "What cruise lines are best for multigenerational families?",
        ],
    },
]


def create_golden_scenario(template: Dict[str, Any]) -> ConversationScenario:
    """Create a ConversationScenario from a golden template."""
    return ConversationScenario(
        scenario_id=f"golden_{template['name']}",
        user_profile=UserProfile(**template["user_profile"]),
        goal=template["goal"],
        constraints=ScenarioConstraints(**template["constraints"]),
        difficulty=DifficultySettings(
            level="medium",
            ambiguity_level="low",
            missing_inputs=[],
            edge_cases=[],
            conflicting_constraints=False,
        ),
        turns=[
            ConversationTurn(turn_number=i + 1, user_message=msg)
            for i, msg in enumerate(template["turns"])
        ],
        expected_outcomes={},
        metadata={"source": "golden_template", "name": template["name"]},
    )


def get_golden_scenarios() -> List[ConversationScenario]:
    """Get all predefined golden scenarios for regression testing."""
    return [create_golden_scenario(t) for t in GOLDEN_SCENARIOS]
