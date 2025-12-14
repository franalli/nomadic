#!/usr/bin/env python3
"""
Evaluate the _is_low_quality_suggestion function with comprehensive test cases.
This helps identify false positives (valid suggestions rejected) and
false negatives (invalid suggestions accepted).
"""

import sys

# Copy of the function to test (avoids import issues)
_ASSISTANT_PHRASES = [
    "i can help",
    "i'll help",
    "i will help",
    "let me",
    "i'll find",
    "i will find",
    "would you like",
    "shall i",
    "i understand",
    "i'll look",
    "i will look",
    "here are",
    "here's",
    "i'll suggest",
    "i will suggest",
]

_VAGUE_PATTERNS = [
    "where would you",
    "what would you",
    "how about",
    "would you prefer",
    "do you have",
    "do you want",
    "are you looking",
    "what kind of",
    "what type of",
]

_INSTRUCTION_STARTS = [
    "please",
    "can you",
    "could you",
    "would you",
    "will you",
    "i need you to",
    "i want you to",
]


def _is_low_quality_suggestion(text: str) -> bool:
    """Check if suggestion is too vague, assistant-style, or instruction-like."""
    lower = text.lower().strip()

    # Reject assistant-style phrases
    for phrase in _ASSISTANT_PHRASES:
        if phrase in lower:
            return True

    # Reject vague/placeholder patterns
    for pattern in _VAGUE_PATTERNS:
        if pattern in lower:
            return True

    # Reject instruction-style starts
    instruction_starts = [
        "add",
        "include",
        "specify",
        "provide",
        "enter",
        "select",
        "choose",
        "consider",
        "try",
        "explore",
        "look for",
        "looking for",
        "search for",
        "find",
        "get",
        "set",
        "update",
        "change",
    ]
    for instruction in instruction_starts:
        if lower.startswith(instruction + " ") or lower.startswith(instruction + " a "):
            return True

    # Reject request patterns (user asking the assistant to do something)
    request_patterns = [
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "will you ",
        "i need you to",
        "i want you to",
        "i'd like you to",
    ]
    for pattern in request_patterns:
        if lower.startswith(pattern):
            return True

    # Reject if too short (less than 2 words) UNLESS it looks like a place name
    # Single-word destinations like "Nepal", "Bali", "Peru" are valid
    words = text.split()
    if len(words) < 2:
        # Reject single letters but allow 2-3 char uppercase abbreviations (LA, NYC, UK)
        if len(text) == 1:
            return True
        # Allow all-uppercase abbreviations (LA, UK, NYC, USA) - valid place codes
        if text.isupper() and len(text) <= 4:
            pass  # Allow these
        elif len(text) <= 2:
            # Reject 2-char lowercase or mixed case (not abbreviations)
            return True
        # Reject pure numbers (like "2", "10", "2024")
        if text.isdigit():
            return True
        # Reject common command words that might be capitalized
        command_words = {
            "go",
            "try",
            "set",
            "get",
            "add",
            "run",
            "use",
            "see",
            "ask",
            "let",
        }
        if lower in command_words:
            return True
        # Allow single words that start with uppercase (proper nouns = places)
        # or are at least 4 characters (likely a place name or valid term)
        if not (text[0].isupper() or len(text) >= 4):
            return True

    # Reject if too many words (more than 8)
    if len(words) > 8:
        return True

    # Reject generic fillers
    generic_fillers = {"yes", "no", "ok", "okay", "sure", "thanks", "thank you"}
    if lower in generic_fillers:
        return True

    # Reject suggestions that are too generic/vague (no concrete nouns)
    # Use word boundary matching to avoid false positives like "Adventure activities"
    vague_phrases = [
        "a specific",
        "the best",
        "some options",
        "more details",
        "more information",
        "something",
        "anything",
        "anywhere",  # too vague without specifics
        "somewhere",  # too vague without specifics
        "preferences",
        "by the beach",  # vague location
        "near the",
        "around the",
    ]
    for vague in vague_phrases:
        if vague in lower:
            return True

    # Reject if ONLY the word "activities" or "destination" (too generic alone)
    # But allow "Adventure activities", "Beach activities", etc.
    if lower == "activities" or lower == "destination":
        return True

    return False


# Test cases: (suggestion_text, should_be_rejected, category)
TEST_CASES = [
    # ==========================================================================
    # VALID DESTINATIONS (should NOT be rejected)
    # ==========================================================================
    ("Tokyo", False, "single-word destination"),
    ("Nepal", False, "single-word destination"),
    ("Bali", False, "single-word destination"),
    ("Peru", False, "single-word destination"),
    ("Paris", False, "single-word destination"),
    ("Nice", False, "single-word destination (France)"),
    ("Split", False, "single-word destination (Croatia)"),
    ("Reading", False, "single-word destination (UK)"),
    ("Bath", False, "single-word destination (UK)"),
    ("Essen", False, "single-word destination (Germany)"),
    ("Como", False, "single-word destination (Italy)"),
    ("Faro", False, "single-word destination (Portugal)"),
    ("Goa", False, "single-word destination (India)"),
    ("NYC", False, "abbreviation destination"),
    ("LA", False, "abbreviation destination"),
    ("UK", False, "abbreviation destination"),
    ("USA", False, "abbreviation destination"),
    ("UAE", False, "abbreviation destination"),
    ("SF", False, "abbreviation destination"),
    ("DC", False, "abbreviation destination"),
    ("New Zealand", False, "multi-word destination"),
    ("Costa Rica", False, "multi-word destination"),
    ("South Africa", False, "multi-word destination"),
    ("The Maldives", False, "destination with article"),
    ("The Bahamas", False, "destination with article"),
    ("Sri Lanka", False, "multi-word destination"),
    ("Hong Kong", False, "multi-word destination"),
    ("New York City", False, "multi-word destination"),
    ("Los Angeles", False, "multi-word destination"),
    ("San Francisco", False, "multi-word destination"),
    ("Buenos Aires", False, "multi-word destination"),
    ("Rio de Janeiro", False, "multi-word destination"),
    ("St. Lucia", False, "destination with abbreviation"),
    ("St Tropez", False, "destination with abbreviation"),
    # ==========================================================================
    # VALID ACTIVITY SUGGESTIONS (should NOT be rejected)
    # ==========================================================================
    ("Beach vacation", False, "activity suggestion"),
    ("Adventure activities", False, "activity suggestion"),
    ("Hiking trails", False, "activity suggestion"),
    ("Scuba diving", False, "activity suggestion"),
    ("Wine tasting tour", False, "activity suggestion"),
    ("Cultural experiences", False, "activity suggestion"),
    ("Northern Lights viewing", False, "activity suggestion"),
    ("Safari trip", False, "activity suggestion"),
    ("Skiing holiday", False, "activity suggestion"),
    ("Snorkeling spots", False, "activity suggestion"),
    ("Historical sites", False, "activity suggestion"),
    ("Food tour", False, "activity suggestion"),
    ("City exploration", False, "activity suggestion"),
    ("Island hopping", False, "activity suggestion"),
    ("Mountain climbing", False, "activity suggestion"),
    ("Water sports", False, "activity suggestion"),
    ("Relaxation spa", False, "activity suggestion"),
    ("Adventure sports", False, "activity suggestion"),
    ("Wildlife watching", False, "activity suggestion"),
    ("Photography tour", False, "activity suggestion"),
    # ==========================================================================
    # VALID DATE SUGGESTIONS (should NOT be rejected)
    # ==========================================================================
    ("Next week", False, "date suggestion"),
    ("December 2024", False, "date suggestion"),
    ("Summer vacation", False, "date suggestion"),
    ("Spring break", False, "date suggestion"),
    ("Christmas holidays", False, "date suggestion"),
    ("January 15th", False, "date suggestion"),
    ("Mid-March", False, "date suggestion"),
    ("Early April", False, "date suggestion"),
    ("Late November", False, "date suggestion"),
    ("First week of May", False, "date suggestion"),
    ("Weekend trip", False, "date suggestion"),
    ("10 days", False, "date suggestion"),
    ("Two weeks", False, "date suggestion"),
    ("A week", False, "date suggestion"),
    ("5 nights", False, "date suggestion"),
    ("3-4 days", False, "date suggestion"),
    # ==========================================================================
    # VALID TRAVELER COUNTS (should NOT be rejected)
    # ==========================================================================
    ("Just myself", False, "traveler count"),
    ("2 people", False, "traveler count"),
    ("Family of 4", False, "traveler count"),
    ("Group of friends", False, "traveler count"),
    ("Couple trip", False, "traveler count"),
    ("Solo travel", False, "traveler count"),
    ("Me and my partner", False, "traveler count"),
    ("4 adults", False, "traveler count"),
    ("2 adults 2 kids", False, "traveler count"),
    ("Just me", False, "traveler count"),
    ("With my family", False, "traveler count"),
    # ==========================================================================
    # VALID BUDGET SUGGESTIONS (should NOT be rejected)
    # ==========================================================================
    ("$5000", False, "budget"),
    ("Budget friendly", False, "budget"),
    ("Luxury travel", False, "budget"),
    ("Mid-range hotels", False, "budget"),
    ("Around $2000 per person", False, "budget"),
    ("Under $3000", False, "budget"),
    ("About $1500", False, "budget"),
    ("5000 USD", False, "budget"),
    ("2000 euros", False, "budget"),
    ("Backpacker budget", False, "budget"),
    ("No specific budget", False, "budget"),
    ("Flexible budget", False, "budget"),
    # ==========================================================================
    # VALID ORIGIN SUGGESTIONS (should NOT be rejected)
    # ==========================================================================
    ("From London", False, "origin suggestion"),
    ("From New York", False, "origin suggestion"),
    ("From Sydney", False, "origin suggestion"),
    ("London Heathrow", False, "origin suggestion"),
    ("JFK Airport", False, "origin suggestion"),
    ("Starting from Paris", False, "origin suggestion"),
    ("Departing from LA", False, "origin suggestion"),
    # ==========================================================================
    # VALID MISC USER RESPONSES (should NOT be rejected)
    # ==========================================================================
    ("I prefer beaches", False, "valid user preference"),
    ("Warm weather", False, "valid user preference"),
    ("Not too crowded", False, "valid user preference"),
    ("Off the beaten path", False, "valid user preference"),
    ("Family friendly", False, "valid user preference"),
    ("Good for kids", False, "valid user preference"),
    ("Romantic getaway", False, "valid user preference"),
    ("Honeymoon destination", False, "valid user preference"),
    ("Bachelor party", False, "valid user preference"),
    ("Anniversary trip", False, "valid user preference"),
    # ==========================================================================
    # INVALID - ASSISTANT PHRASES (should be rejected)
    # ==========================================================================
    ("I can help you", True, "assistant phrase"),
    ("Let me know if you", True, "assistant phrase"),
    ("Would you like me to", True, "assistant phrase"),
    ("I'll find some options", True, "assistant phrase"),
    ("Here are some suggestions", True, "assistant phrase"),
    ("I understand you want", True, "assistant phrase"),
    ("I can help with that", True, "assistant phrase"),
    ("Let me find that for you", True, "assistant phrase"),
    ("I'll look into that", True, "assistant phrase"),
    ("I will help you plan", True, "assistant phrase"),
    ("Here's what I found", True, "assistant phrase"),
    ("I'll suggest some places", True, "assistant phrase"),
    ("Shall I continue?", True, "assistant phrase"),
    # ==========================================================================
    # INVALID - TOO VAGUE (should be rejected)
    # ==========================================================================
    ("Something nice", True, "too vague"),
    ("Anywhere warm", True, "too vague"),
    ("The best places", True, "too vague"),
    ("Some options", True, "too vague"),
    ("More details", True, "too vague"),
    ("More information", True, "too vague"),
    ("Somewhere tropical", True, "too vague"),
    ("Anywhere in Europe", True, "too vague"),
    ("Something relaxing", True, "too vague"),
    ("Anything adventurous", True, "too vague"),
    ("A specific destination", True, "too vague"),
    ("What are your preferences", True, "too vague"),
    ("Near the beach", True, "too vague"),
    ("Around the city", True, "too vague"),
    ("By the beach please", True, "too vague"),
    # ==========================================================================
    # INVALID - GENERIC FILLERS (should be rejected)
    # ==========================================================================
    ("Yes", True, "generic filler"),
    ("No", True, "generic filler"),
    ("Ok", True, "generic filler"),
    ("Okay", True, "generic filler"),
    ("Sure", True, "generic filler"),
    ("Thanks", True, "generic filler"),
    ("Thank you", True, "generic filler"),
    # ==========================================================================
    # INVALID - INSTRUCTION-LIKE (should be rejected)
    # ==========================================================================
    ("Please tell me about", True, "instruction-like"),
    ("Could you find", True, "instruction-like"),
    ("Can you suggest", True, "instruction-like"),
    ("I need you to", True, "instruction-like"),
    ("I want you to help", True, "instruction-like"),
    ("Please help me", True, "instruction-like"),
    ("Would you recommend", True, "instruction-like"),
    ("Will you find", True, "instruction-like"),
    ("I'd like you to search", True, "instruction-like"),
    ("Find a hotel", True, "instruction-like"),
    ("Get me flights", True, "instruction-like"),
    ("Add another day", True, "instruction-like"),
    ("Include museums", True, "instruction-like"),
    ("Choose a beach", True, "instruction-like"),
    ("Select hotels", True, "instruction-like"),
    ("Explore options", True, "instruction-like"),
    ("Look for cheap flights", True, "instruction-like"),
    ("Search for hostels", True, "instruction-like"),
    ("Update the itinerary", True, "instruction-like"),
    ("Change the dates", True, "instruction-like"),
    # ==========================================================================
    # INVALID - TOO SHORT / EMPTY (should be rejected)
    # ==========================================================================
    ("a", True, "too short"),
    ("", True, "empty"),
    ("   ", True, "whitespace only"),
    ("x", True, "single letter"),
    ("hi", True, "too short greeting"),
    ("yo", True, "too short slang"),
    ("um", True, "filler word"),
    ("uh", True, "filler word"),
    # ==========================================================================
    # INVALID - SINGLE LETTERS (should be rejected)
    # ==========================================================================
    ("I", True, "single letter - pronoun"),
    ("A", True, "single letter - article"),
    ("An", True, "two letters - article"),
    # ==========================================================================
    # INVALID - COMMAND WORDS (should be rejected)
    # ==========================================================================
    ("Go", True, "command word"),
    ("Try", True, "command word"),
    ("Set", True, "command word"),
    ("Get", True, "command word"),
    ("Add", True, "command word"),
    ("Run", True, "command word"),
    ("Use", True, "command word"),
    ("See", True, "command word"),
    ("Ask", True, "command word"),
    ("Let", True, "command word"),
    # ==========================================================================
    # INVALID - PURE NUMBERS (should be rejected)
    # ==========================================================================
    ("2", True, "pure number"),
    ("10", True, "pure number"),
    ("100", True, "pure number"),
    ("2024", True, "year alone - too vague"),
    ("2025", True, "year alone - too vague"),
    ("123", True, "pure number"),
    # ==========================================================================
    # INVALID - STANDALONE GENERIC WORDS (should be rejected)
    # ==========================================================================
    ("activities", True, "generic word alone"),
    ("Activities", True, "generic word alone capitalized"),
    ("destination", True, "generic word alone"),
    ("Destination", True, "generic word alone capitalized"),
    # ==========================================================================
    # INVALID - QUESTION PATTERNS (should be rejected)
    # ==========================================================================
    ("Where would you like to go", True, "question pattern"),
    ("What would you prefer", True, "question pattern"),
    ("How about a beach", True, "question pattern"),
    ("Would you prefer luxury", True, "question pattern"),
    ("Do you have a budget", True, "question pattern"),
    ("Do you want me to", True, "question pattern"),
    ("Are you looking for adventure", True, "question pattern"),
    ("What kind of trip", True, "question pattern"),
    ("What type of activities", True, "question pattern"),
    # ==========================================================================
    # INVALID - TOO LONG (should be rejected - more than 8 words)
    # ==========================================================================
    (
        "I would really love to visit a beautiful tropical beach destination with amazing food",
        True,
        "too long",
    ),
    (
        "A nice quiet secluded beach resort with great food and activities for the whole family",
        True,
        "too long",
    ),
    # ==========================================================================
    # EDGE CASES - VALID SINGLE WORDS (context-dependent, should be accepted)
    # ==========================================================================
    ("Beach", False, "single generic noun - could be valid"),
    ("Mountain", False, "single generic noun - could be valid"),
    ("City", False, "single generic noun - could be valid"),
    ("Island", False, "single generic noun - could be valid"),
    ("Resort", False, "single generic noun - could be valid"),
    ("Cruise", False, "single generic noun - could be valid"),
    ("Safari", False, "single generic noun - could be valid"),
    ("Camping", False, "single generic noun - could be valid"),
    ("Hiking", False, "single generic noun - could be valid"),
    ("Diving", False, "single generic noun - could be valid"),
    ("Surfing", False, "single generic noun - could be valid"),
    ("Skiing", False, "single generic noun - could be valid"),
    # ==========================================================================
    # EDGE CASES - MIXED CASE ABBREVIATIONS (valid)
    # ==========================================================================
    ("NYC", False, "all caps abbreviation - valid"),
    ("USA", False, "all caps abbreviation - valid"),
    ("UAE", False, "all caps abbreviation - valid"),
    # ==========================================================================
    # EDGE CASES - SPECIAL CHARACTERS (should be accepted if meaningful)
    # ==========================================================================
    ("$500-1000", False, "budget range with special chars"),
    ("St. Martin", False, "destination with period"),
    ("Côte d'Azur", False, "destination with accents"),
    # ==========================================================================
    # EDGE CASES - NUMBERS WITH CONTEXT (should be accepted)
    # ==========================================================================
    ("2 weeks", False, "number with context"),
    ("3 people", False, "number with context"),
    ("5 star hotels", False, "number with context"),
    ("4 days", False, "number with context"),
    ("Route 66", False, "number in name"),
    # ==========================================================================
    # EDGE CASES - LOWERCASE PLACE NAMES (some cities are lowercase-ish)
    # ==========================================================================
    ("tokyo", False, "lowercase destination - should still work"),
    ("paris", False, "lowercase destination - should still work"),
    ("bali", False, "lowercase destination - should still work"),
]


def main():
    issues = []
    edge_cases = []

    print("=" * 60)
    print("EVALUATING _is_low_quality_suggestion()")
    print("=" * 60)
    print()

    for text, should_reject, category in TEST_CASES:
        result = _is_low_quality_suggestion(text)

        # Check if result matches expectation
        if result != should_reject:
            issues.append(
                {
                    "text": text,
                    "category": category,
                    "expected": "REJECTED" if should_reject else "ACCEPTED",
                    "actual": "REJECTED" if result else "ACCEPTED",
                }
            )

        # Flag edge cases for review
        if "could be" in category.lower() or "context" in category.lower():
            edge_cases.append(
                {
                    "text": text,
                    "category": category,
                    "result": "REJECTED" if result else "ACCEPTED",
                }
            )

    # Report issues
    if issues:
        print(f"❌ ISSUES FOUND: {len(issues)}")
        print("-" * 40)
        for issue in issues:
            print(f"  '{issue['text']}' ({issue['category']})")
            print(f"    Expected: {issue['expected']}, Got: {issue['actual']}")
        print()
    else:
        print("✅ All test cases passed!")
        print()

    # Report edge cases
    if edge_cases:
        print(f"⚠️  EDGE CASES for manual review: {len(edge_cases)}")
        print("-" * 40)
        for ec in edge_cases:
            print(f"  '{ec['text']}' ({ec['category']}) -> {ec['result']}")
        print()

    # Summary
    total = len(TEST_CASES)
    passed = total - len(issues)
    print(f"Summary: {passed}/{total} test cases matched expectations")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
