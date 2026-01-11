"""
Pattern Matching Module for Trip Input Extraction.

This module consolidates all regex patterns used for deterministic extraction
of trip planning inputs. These patterns enable fast-path extraction without
LLM calls for common user inputs.

Sections:
    1. UTILITY PATTERNS - Common patterns (ANSI escape, sentence endings, etc.)
    2. SHORT-CIRCUIT PATTERNS - Greeting/yes/no detection for quick responses
    3. DATE PATTERNS - Relative dates, seasons, months
    4. TRAVELER PATTERNS - Solo, couple, family, group detection
    5. BUDGET PATTERNS - Currency, amounts, budget phrases
    6. DURATION PATTERNS - Days, nights, weeks
    7. DESTINATION PATTERNS - Place extraction, origin/destination
    8. FLIGHT PATTERNS - Cabin class, layovers, airline preferences
    9. HOTEL PATTERNS - Star ratings, amenities, room preferences
    10. TRANSPORT PATTERNS - Car rental, train, ferry, bus
    11. ACTIVITY PATTERNS - Tours, museums, specific activities
    12. INFEASIBILITY PATTERNS - Impossible requests detection
    13. LQA (Last Question Answer) PATTERNS - Field-specific answer patterns
"""

import re
from typing import Dict, FrozenSet, List, Pattern, Tuple

# =============================================================================
# 1. UTILITY PATTERNS
# =============================================================================

# ANSI escape codes (terminal colors, formatting)
ANSI_ESCAPE_PATTERN = re.compile(r"(\x1b|\x9b)\[[0-9;:]*[A-Za-z]")

# Sentence-ending punctuation (used to detect full sentences vs fragments)
SENTENCE_ENDING_PATTERN = re.compile(r"[!?]\s*$")

# Strip leading articles from destinations ("the Netherlands" -> "Netherlands")
ARTICLE_PREFIX_PATTERN = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)

# Verb patterns that indicate a sentence (not a place list)
SENTENCE_VERB_PATTERN = re.compile(
    r"\b(want|go|plan|visit|travel|explore|see|book|need|would|could|should|"
    r"will|can|am|is|are)\b",
    re.IGNORECASE,
)

# Multi-place separators for splitting destination lists
PLACE_SEPARATORS_PATTERN = re.compile(r"\s*(?:,|/|\band\b|&|\+)\s*", re.IGNORECASE)


# =============================================================================
# 2. SHORT-CIRCUIT PATTERNS
# =============================================================================
# Patterns for quick response without full LLM processing

GREETING_PATTERN = re.compile(
    r"^(h(i|ey|ello|iya|owdy)|yo|sup|good\s+(morning|afternoon|evening|day)|"
    r"what'?s\s+up|greetings?)[\s\.\!\?]*$",
    re.IGNORECASE,
)

YES_PATTERN = re.compile(
    r"^(yes|yeah|yep|yup|yea|ya|sure|ok(ay)?|alright|all\s+right|"
    r"sounds?\s+good|absolutely|definitely|of\s+course|please|do\s+it|go\s+ahead|"
    r"let'?s\s+do\s+(it|this|that)|ok(ay)?\s+go\s+ahead)[\s\.\!\?]*$",
    re.IGNORECASE,
)

NO_PATTERN = re.compile(
    r"^(no|nope|nah|not\s+really|no\s+thanks?|never\s*mind|cancel|"
    r"don'?t|stop|wait|hold\s+on)[\s\.\!\?]*$",
    re.IGNORECASE,
)

# Generate request pattern - detect explicit plan generation requests
# Matches: "generate my itinerary", "create my plan", "show me the plan",
# "I'm ready", "looks good, go ahead", "let's go", "book it now", etc.
# IMPORTANT: Avoid matching multi-city intent phrases like "do it all together"
GENERATE_REQUEST_PATTERN = re.compile(
    r"(?:"
    # "yes, generate my itinerary" / "generate my plan" / "create the itinerary"
    r"(?:yes[,!]?\s+)?(?:generate|create|build|make)\s+(?:my\s+|the\s+)?(?:itinerary|plan|trip)"
    r"|"
    # "show me the plan" / "show the itinerary"
    r"(?:show|give)\s+(?:me\s+)?(?:the\s+)?(?:plan|itinerary)" r"|"
    # "I'm ready" / "ready to go" / "ready to generate"
    r"(?:i'?m\s+)?ready(?:\s+to\s+(?:go|book|generate|plan))?" r"|"
    # "looks good, go ahead" / "sounds good, let's go"
    r"(?:looks?|sounds?)\s+good[,!]?\s*(?:go\s+ahead|let'?s\s+(?:go|do\s+it))?" r"|"
    # "let's go" / "let's do it" / "let's book"
    r"let'?s\s+(?:go|do\s+it|book|plan|generate)" r"|"
    # "go ahead" / "go ahead and generate"
    r"go\s+ahead(?:\s+(?:and\s+)?(?:generate|create|book|plan))?" r"|"
    # "book it" / "book it now"
    r"book\s+it(?:\s+now)?" r"|"
    # "do it now" / "make it happen" (NOT "do it all together" which is multi-city intent)
    r"(?:do|make)\s+it\s+(?:now|happen)" r"|"
    # "yes please generate" / "yes generate"
    r"yes[,!]?\s*(?:please\s+)?generate" r")",
    re.IGNORECASE,
)

# Patterns indicating complex/dense input
COMMA_LIST_PATTERN = re.compile(r",\s*(?:and\s+)?[A-Z][a-z]+", re.IGNORECASE)
MULTI_DESTINATION_PATTERN = re.compile(r"\b(?:and|then|also|plus)\s+[A-Z][a-z]+", re.IGNORECASE)


# =============================================================================
# 3. DATE PATTERNS
# =============================================================================

# Relative date patterns for deterministic parsing
RELATIVE_DATE_PATTERNS: Dict[str, Pattern] = {
    "next_month": re.compile(r"^next\s+month$", re.IGNORECASE),
    "this_month": re.compile(r"^this\s+month$", re.IGNORECASE),
    "next_week": re.compile(r"^next\s+week$", re.IGNORECASE),
    "this_weekend": re.compile(r"^this\s+weekend$", re.IGNORECASE),
    "next_weekend": re.compile(r"^next\s+weekend$", re.IGNORECASE),
    "tomorrow": re.compile(r"^tomorrow$", re.IGNORECASE),
    "today": re.compile(r"^today$", re.IGNORECASE),
    # "next monday", "next tuesday", etc.
    "next_weekday": re.compile(
        r"^next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$",
        re.IGNORECASE,
    ),
    # "this monday", "this tuesday", etc.
    "this_weekday": re.compile(
        r"^this\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$",
        re.IGNORECASE,
    ),
}

# Season patterns (spring, summer, fall/autumn, winter)
SEASON_PATTERN = re.compile(
    r"^(?:this\s+|next\s+)?(spring|summer|fall|autumn|winter)(?:\s+\d{4})?$",
    re.IGNORECASE,
)

# Month name pattern
MONTH_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)

# =============================================================================
# RELATIVE DATE WORDS (Single Source of Truth)
# =============================================================================
# These standalone words indicate a date answer when user is asked about dates.
# Used by: DATES_COMPATIBILITY_PATTERN, text_is_compatible_with_target,
#          _is_date_like_text (via is_text_date_compatible)
# =============================================================================
RELATIVE_DATE_WORDS_SIMPLE = frozenset(
    {
        "today",
        "tomorrow",
        "tonight",
        "weekend",
    }
)

# Extended relative date words (require context like "next" or "this")
RELATIVE_DATE_WORDS_CONTEXTUAL = frozenset(
    {
        "week",
        "month",
        "year",
        "morning",
        "evening",
        "afternoon",
        "night",
    }
)

# Combined set for general date-like detection
RELATIVE_DATE_WORDS_ALL = (
    RELATIVE_DATE_WORDS_SIMPLE
    | RELATIVE_DATE_WORDS_CONTEXTUAL
    | {
        "next",
        "this",  # Modifiers that signal date context
    }
)

# Date compatibility pattern (for question-target matching)
# NOTE: This is the canonical pattern for checking if text answers a dates question.
DATES_COMPATIBILITY_PATTERN = re.compile(
    r"(?:"
    # Standalone relative date words (tomorrow, today, tonight, weekend)
    r"\b(?:today|tomorrow|tonight|weekend)\b|"
    # Full month names
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b|"
    # Abbreviated month names
    r"\b(?:jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b|"
    # Relative phrases with "next"
    r"\bnext\s+(?:week|month|year|summer|winter|spring|fall|autumn)\b|"
    # Relative phrases with "this"
    r"\bthis\s+(?:week|month|year|summer|winter|spring|fall|autumn)\b|"
    r"\bfirst\s+week\s+of\b|"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|"  # Date formats like 12/25/2024
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b|"  # ISO dates like 2024-12-25
    r"\bholiday\b|"
    # Seasons (standalone)
    r"\b(?:spring|summer|fall|autumn|winter)\b|"
    # Flexibility expressions
    r"\b(?:flexible|whenever|anytime)\b" r")",
    re.IGNORECASE,
)

# Date range pattern (e.g., "Dec 15-22", "15th to 22nd December", "December 15 through 22")
DATE_RANGE_PATTERN = re.compile(
    r"(?:"
    # "Dec 15-22" or "December 15-22"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\b|"
    # "15-22 December" or "15th-22nd December"
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s*[-–—]\s*(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b|"
    # "15th to 22nd December" or "December 15 to 22"
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:to|through|thru|until|till)\s+(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b|"
    # "December 15 to 22" or "Dec 15 through 22"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:to|through|thru|until|till)\s+(\d{1,2})(?:st|nd|rd|th)?\b"
    r")",
    re.IGNORECASE,
)

# Ordinal date pattern (e.g., "15th December", "the 15th", "December 15th")
ORDINAL_DATE_PATTERN = re.compile(
    r"(?:"
    # "15th December" or "the 15th of December"
    r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\s+(?:of\s+)?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b|"
    # "December 15th"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)\b"
    r")",
    re.IGNORECASE,
)

# Flexible/open dates pattern
FLEXIBLE_DATES_PATTERN = re.compile(
    r"(?:"
    r"\b(flexible|open)\s+(?:on\s+)?dates?\b|"
    r"\bdates?\s+(?:are\s+)?(?:flexible|open)\b|"
    r"\bany\s+time\s+in\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b|"
    r"\bsometime\s+in\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b|"
    r"\bdon'?t\s+have\s+(?:specific|exact)\s+dates?\b|"
    r"\bno\s+(?:specific|exact|fixed)\s+dates?\b|"
    r"\bwhenever\s+works\b|"
    r"\bflexible\s+(?:with|on|about)\s+(?:the\s+)?(?:dates?|timing|when)\b"
    r")",
    re.IGNORECASE,
)

# European date format (dd/mm/yyyy or dd-mm-yyyy)
EURO_DATE_PATTERN = re.compile(
    r"\b(0?[1-9]|[12]\d|3[01])[/\-](0?[1-9]|1[0-2])[/\-](\d{4}|\d{2})\b",
    re.IGNORECASE,
)


# =============================================================================
# 4. TRAVELER PATTERNS
# =============================================================================

# Basic travelers pattern (standalone answers like "just me", "2 adults")
TRAVELERS_PATTERN = re.compile(
    r"^(?:just\s+me|only\s+me|me|myself|solo|"
    r"a?\s*couple|"
    r"(\d+)\s*(adult|person|people|guest|traveler|pax)s?|"
    r"(?:family\s+of|group\s+of)\s+(\d+)|"
    r"(\d+)\s*(?:of\s+us|traveling))$",
    re.IGNORECASE,
)

# Inline travelers within sentences
INLINE_TRAVELERS_PATTERN = re.compile(
    r"(?:^|[\s,])(?:"
    # Solo indicators
    r"(?:i'?m\s+)?(?:traveling\s+)?(?:solo|alone|by\s+myself)|"
    r"solo\s+(?:trip|travel|vacation)|"
    r"just\s+(?:me|myself)(?:\s+going|\s+traveling)?|"
    r"on\s+my\s+own|"
    # Couple indicators
    r"(?:my\s+)?(?:partner|spouse|husband|wife|boyfriend|girlfriend)\s+and\s+(?:i|me)|"
    r"(?:i|me)\s+and\s+my\s+(?:partner|spouse|husband|wife|boyfriend|girlfriend)|"
    r"(?:the\s+)?two\s+of\s+us|"
    r"just\s+(?:the\s+)?two\s+(?:of\s+us)?|"
    r"as\s+a\s+couple|"
    # Family with numbers
    r"(?:family\s+of|group\s+of|party\s+of)\s+(\d+)|"
    r"(\d+)\s+(?:of\s+us|people|adults?|travelers?)(?:\s+(?:are|will))?|"
    # Explicit counts
    r"(?:there\s+(?:are|will\s+be)\s+)?(\d+)\s+of\s+us" r")(?:[\s,.]|$)",
    re.IGNORECASE,
)

# Family composition pattern
FAMILY_COMPOSITION_PATTERN = re.compile(
    r"(?:"
    # "family of N" / "family with N members"
    r"family\s+(?:of|with)\s+(\d+)(?:\s+(?:people|members))?|"
    # "N adults and N kids/children"
    r"(\d+)\s*adults?\s*(?:and|with|&|\+)\s*(\d+)\s*(?:kids?|children|child)|"
    # "me and my N kids" / "myself and N children"
    r"(?:me|myself|i)\s+(?:and\s+)?(?:my\s+)?(\d+)\s*(?:kids?|children|child)|"
    # "with N kids/children" / "have N kids with us" / "we have N kids"
    r"(?:with|have)\s+(\d+|two|three|four)\s*(?:kids?|children|child)(?:\s+with\s+us)?|"
    # "N kids with us"
    r"(\d+|two|three|four)\s*(?:kids?|children|child)\s+with\s+us|"
    # "traveling with kids/children" (implies children, count unknown)
    r"((?:traveling|going)\s+with\s+(?:the\s+)?(?:kids?|children))|"
    # "for the kids" / "our kids" / "the kids" (implies children)
    r"((?:for|with|and)\s+(?:the|our|my)\s+(?:kids?|children))|"
    # "family trip" / "family vacation" (implies children likely)
    r"(family\s+(?:trip|vacation|holiday|getaway))" r")",
    re.IGNORECASE,
)

# Travelers with kids (e.g., "2 adults and 2 kids")
TRAVELERS_WITH_KIDS_PATTERN = re.compile(
    r"^(\d+)\s*adults?\s*(?:and|with|&|\+)\s*(\d+)\s*(?:kids?|children|child)$",
    re.IGNORECASE,
)

# Traveler detail pattern (e.g., "3 kids ages 5, 8, 12")
TRAVELER_DETAIL_PATTERN = re.compile(
    r"\b(?:kids?|children|child)\b.*\bages?\b.*\d+(?:\s*,\s*\d+)+",
    re.IGNORECASE,
)

# Ages-only pattern (e.g., "ages 3, 6, 12" or just "3, 6, 12")
TRAVELER_AGES_ONLY_PATTERN = re.compile(
    r"^\s*(?:ages?\s*)?\d+(?:\s*,\s*(?:and\s*)?\d+)+\s*$",
    re.IGNORECASE,
)

# Travelers micro-patterns for LQA parsing
TRAVELERS_MICRO_PATTERNS: Dict[str, Pattern] = {
    "solo": re.compile(
        r"^(?:solo|just\s+me|only\s+me|me|myself|alone|by\s+myself)$", re.IGNORECASE
    ),
    "couple": re.compile(
        r"^(?:couple|2\s+of\s+us|two\s+of\s+us|me\s+and\s+(?:my\s+)?"
        r"(?:partner|spouse|wife|husband|boyfriend|girlfriend))$",
        re.IGNORECASE,
    ),
    "family": re.compile(r"^family\s+of\s+(\d+)$", re.IGNORECASE),
    "group": re.compile(r"^(\d+)\s*(?:people|adults?|travelers?|of\s+us)$", re.IGNORECASE),
}

# Travelers compatibility pattern (for question-target matching)
TRAVELERS_COMPATIBILITY_PATTERN = re.compile(
    r"(?:"
    r"\bjust\s+me\b|"
    r"\bsolo\b|"
    r"\bcouple\b|"
    r"\b\d+\s*(?:adults?|people|persons?|travelers?|travellers?)\b|"
    r"\bfamily\s+of\s+\d+\b|"
    r"\b\d+\s*(?:kids?|children|child)\b|"
    r"\bages?\s+\d+"
    r")",
    re.IGNORECASE,
)

# Age-qualified children patterns (e.g., "kids under 12", "toddler", "infant")
AGE_QUALIFIED_PATTERN = re.compile(
    r"(?:"
    # Age ranges: "kids under 12", "children aged 5-10", "kids between 3 and 8"
    r"\b(?:kids?|children|child)\s+(?:under|below|younger\s+than)\s+(\d{1,2})\b|"
    r"\b(?:kids?|children|child)\s+(?:over|above|older\s+than)\s+(\d{1,2})\b|"
    r"\b(?:kids?|children|child)\s+(?:aged?|ages?)\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\b|"
    r"\b(?:kids?|children|child)\s+between\s+(\d{1,2})\s+and\s+(\d{1,2})\b|"
    # Specific age categories
    r"\b(infant|infants|baby|babies)\b|"
    r"\b(toddler|toddlers)\b|"
    r"\b(teenager|teenagers|teens?|adolescent)\b|"
    r"\b(young\s+(?:kids?|children)|little\s+(?:kids?|ones?))\b|"
    # Senior/elderly
    r"\b(senior|seniors|elderly|older\s+(?:adults?|travelers?|travellers?))\b|"
    r"\b(senior\s+citizen|pensioner|retiree)s?\b|"
    r"\baged?\s+(\d{2})\+?\b"
    r")",
    re.IGNORECASE,
)

# Trip occasion/group type patterns
TRIP_OCCASION_PATTERN = re.compile(
    r"(?:"
    # Celebrations
    r"\b(bachelor|bachelorette|stag|hen)\s+(?:party|trip|weekend)\b|"
    r"\b(wedding|honeymoon|anniversary)\s*(?:trip|vacation|getaway)?\b|"
    r"\b(birthday|graduation|retirement)\s*(?:trip|celebration|getaway)?\b|"
    # Work-related
    r"\b(work|business|corporate)\s+(?:trip|travel|meeting)\b|"
    r"\b(conference|convention|seminar|team\s+building)\b|"
    r"\b(offsite|company\s+retreat|work\s+retreat)\b|"
    # Group types
    r"\b(girls?|guys?|boys?|ladies|lads)\s*(?:trip|weekend|getaway)\b|"
    r"\b(friends|buddies|mates)\s+(?:trip|vacation|getaway)\b|"
    r"\b(group\s+of\s+friends|friend\s+group)\b|"
    # Special events
    r"\b(reunion|gathering|celebration)\b|"
    r"\b(destination\s+wedding|wedding\s+guests?)\b|"
    r"\b(spring\s+break|gap\s+year|sabbatical)\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 5. BUDGET PATTERNS
# =============================================================================

# Basic budget pattern (standalone answers like "$2000", "5k")
BUDGET_PATTERN = re.compile(
    (
        r"^(?:under|around|about|approximately|roughly|up\s*to|less\s+than|"
        r"max(?:imum)?|no\s+more\s+than|~)?\s*"  # Optional qualitative prefix
        r"(?:\$|€|£|USD|EUR|GBP|CAD|AUD)?\s*"  # Optional currency symbol/code before
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k|\d+\s*thousand)"  # Amount
        r"\s*(?:\$|€|£|USD|EUR|GBP|CAD|AUD|dollars?|euros?|pounds?)?"  # Optional after
        r"(?:\s*(?:budget|total|max|maximum|per\s+person|pp))?$"  # Optional suffix
    ),
    re.IGNORECASE,
)

# Inline budget mentions within sentences
INLINE_BUDGET_PATTERN = re.compile(
    (
        r"(?:"  # inline budget patterns
        r"budget\s+(?:of|is|around|about|roughly)?\s*(?:\$|€|£)?"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)\s*(?:\$|€|£|dollars?|euros?|pounds?)?|"
        r"(?:with\s+(?:a\s+)?)?(?:\$|€|£)"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)\s*(?:budget|max|maximum)|"
        # "around/about $X" in context of budget
        r"(?:around|about|roughly|approximately)\s*(?:\$|€|£)"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # "spending/spend $X" / "spend around $X"
        r"(?:spend(?:ing)?|invest(?:ing)?)\s*(?:around|about|roughly)?\s*(?:\$|€|£)?"
        r"(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # "under $X" / "less than $X" / "keep it under $X" / "max $X"
        r"(?:under|less\s+than|no\s+more\s+than|max(?:imum)?|"
        r"keep\s+(?:it|everything|the\s+total|the\s+budget|things|costs?)?\s*under|"
        r"hoping\s+to\s+keep\s+(?:it|the\s+total|everything|things)?\s*under)"
        r"\s*(?:\$|€|£)?(\d+(?:,\d{3})*(?:\.\d{2})?|\d+k)|"
        # Simple "$X" or "$X for the trip/total" - standalone currency amounts
        r"(?:\$|€|£)(\d+(?:,\d{3})*)\s*(?:for\s+(?:the\s+)?"
        r"(?:trip|total|everything|whole|entire)|total)?|"
        # "X dollars/euros" without context
        r"(\d+(?:,\d{3})*)\s*(?:dollars?|euros?|pounds?)"
        r")"
    ),
    re.IGNORECASE,
)

# Budget compatibility pattern (for question-target matching)
# Updated to include flexible/no-budget phrases from FLEXIBLE_BUDGET_PHRASES
BUDGET_COMPATIBILITY_PATTERN = re.compile(
    r"(?:"
    r"[\$€£¥₹]|"  # Currency symbols
    r"\b\d+(?:k|K)?\s*(?:dollars?|euros?|pounds?)\b|"  # Numbers WITH currency (require unit)
    # Flexible budget phrases (canonical patterns from FLEXIBLE_BUDGET_PHRASES)
    # "no budget", "no limit", "no specific budget", "no preference", "no idea"
    r"\bno\s*(?:specific\s*)?(?:budget|limit|preference|max(?:imum)?|constraints?|spending\s*limit|idea)\b|"
    r"\bflexible(?:\s*budget)?\b|"  # "flexible", "flexible budget"
    r"\bunlimited\b|"  # "unlimited"
    r"\bany\s*budget\b|"  # "any budget"
    r"\bdon'?t\s*care\b|"  # "don't care", "dont care"
    r"\bdoesn'?t\s*(?:really\s*)?matter\b|"  # "doesn't matter", "doesn't really matter"
    r"\bwhatever\s*works\b|"  # "whatever works"
    # "money is not an issue", "money isn't an issue"
    r"\bmoney\s*(?:is\s*)?(?:not|n'?t)\s*(?:an?\s*)?(?:issue|object|important)\b|"
    r"\bmoney\s*is\s*no\s*object\b|"  # "money is no object"
    r"\bprice\s*(?:is\s*)?(?:not|doesn'?t)\s*(?:matter|important)\b|"  # "price doesn't matter"
    r"\bopen(?:\s*budget)?\b|"  # "open", "open budget"
    r"\bskip\b|"  # "skip"
    r"\bpass\b|"  # "pass"
    r"\bnot\s*(?:sure|decided)\b|"  # "not sure", "not decided"
    r"\bhaven'?t\s*decided\b|"  # "haven't decided", "havent decided"
    # Budget tier phrases (canonical patterns from BUDGET_TIER_PHRASES)
    r"\bbudget[- ]?friendly\b|"  # "budget-friendly", "budget friendly"
    r"\bcheap(?:est)?\b|"  # "cheap", "cheapest"
    r"\blow[- ]?budget\b|"  # "low-budget", "low budget"
    r"\beconom(?:y|ical)\b|"  # "economy", "economical"
    r"\bmid[- ]?range\b|"  # "mid-range", "midrange", "mid range"
    r"\bmoderate\b|"  # "moderate"
    r"\baverage\b|"  # "average"
    r"\bstandard\b|"  # "standard"
    r"\breasonable\b|"  # "reasonable"
    r"\bluxur(?:y|ious)\b|"  # "luxury", "luxurious"
    r"\bhigh[- ]?end\b|"  # "high-end", "high end"
    r"\bpremium\b|"  # "premium"
    r"\bupscale\b|"  # "upscale"
    r"\bsplurge\b|"  # "splurge"
    r"\b(?:no\s*expense\s*spared|spare\s*no\s*expense)\b|"  # "no expense spared"
    r"\bfirst\s*class\b|"  # "first class"
    r"\btop\s*tier\b|"  # "top tier"
    # Numeric qualifiers (require context)
    r"\baffordable\b|"  # "affordable"
    r"\bexpensive\b|"  # "expensive"
    r"\baround\s+[\$€£¥₹]?\d|"  # "around $X"
    r"\bunder\s+[\$€£¥₹]?\d|"  # "under $X"
    r"\babout\s+[\$€£¥₹]?\d|"  # "about $X"
    r"\bper\s+(?:person|night|day)\b"  # "per person", "per night", "per day"
    r")",
    re.IGNORECASE,
)

# =============================================================================
# FLEXIBLE BUDGET PHRASES (No constraint / open-ended answers)
# =============================================================================
# These phrases indicate the user has no specific budget constraint.
# Used for: LQA parsing, compatibility checks, setting budget_answered=True

FLEXIBLE_BUDGET_PHRASES: FrozenSet[str] = frozenset(
    {
        "no budget",
        "no limit",
        "flexible",
        "flexible budget",
        "no specific budget",
        "unlimited",
        "no preference",
        "any budget",
        "doesn't matter",
        "doesn't really matter",
        "don't care",
        "not sure",
        "not decided",
        "haven't decided",
        "no idea",
        "skip",
        "pass",
        "whatever works",
        "open",
        "open budget",
        "no max",
        "no maximum",
        "no constraints",
        "no spending limit",
        "money is not an issue",
        "money isn't an issue",
        "price doesn't matter",
        "price is not important",
    }
)

# =============================================================================
# BUDGET TIER PHRASES (Qualitative tier indicators)
# =============================================================================
# These phrases indicate a budget tier/preference without a specific amount.
# Used for: LQA parsing, compatibility checks, inferring budget preferences

BUDGET_TIER_PHRASES: FrozenSet[str] = frozenset(
    {
        "budget-friendly",
        "budget friendly",
        "cheap",
        "cheapest",
        "as cheap as possible",
        "low budget",
        "low-budget",
        "economical",
        "economy",
        "mid-range",
        "midrange",
        "mid range",
        "moderate",
        "average",
        "standard",
        "reasonable",
        "luxury",
        "luxurious",
        "high-end",
        "high end",
        "premium",
        "splurge",
        "no expense spared",
        "money is no object",
        "spare no expense",
        "first class",
        "top tier",
        "upscale",
    }
)

# Qualitative budget phrases mapped to numeric estimates (in USD)
BUDGET_TIER_ESTIMATES: Dict[str, int] = {
    # Low tier phrases -> budget-conscious estimates
    "limited budget": 1500,
    "tight budget": 1500,
    "small budget": 1500,
    "budget-friendly": 1500,
    "budget friendly": 1500,
    "cheap": 1000,
    "cheapest": 800,
    "as cheap as possible": 800,
    "low budget": 1200,
    "low-budget": 1200,
    "economical": 1500,
    "economy": 1500,
    # Mid tier phrases -> moderate estimates
    "moderate": 3000,
    "mid-range": 3000,
    "midrange": 3000,
    "mid range": 3000,
    "average": 2500,
    "standard": 2500,
    "reasonable": 2500,
    # High tier phrases -> luxury estimates
    "luxury": 8000,
    "luxurious": 8000,
    "high-end": 10000,
    "high end": 10000,
    "premium": 7000,
    "splurge": 10000,
    "no expense spared": 15000,
    "money is no object": 15000,
    "spare no expense": 15000,
    "first class": 10000,
    "top tier": 10000,
    "upscale": 8000,
}

# =============================================================================
# NO_BUDGET_PHRASES (Backward compatibility union)
# =============================================================================
# Union of FLEXIBLE_BUDGET_PHRASES and BUDGET_TIER_PHRASES for backward
# compatibility with existing code that imports NO_BUDGET_PHRASES.

NO_BUDGET_PHRASES: FrozenSet[str] = FLEXIBLE_BUDGET_PHRASES | BUDGET_TIER_PHRASES


# =============================================================================
# 6. DURATION PATTERNS
# =============================================================================

# Duration pattern (e.g., "7 days", "one week", "10 nights")
DURATION_PATTERN = re.compile(
    r"^(?:(?:for\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(day|days|night|nights|week|weeks))"
    r"(?:\s*(?:trip|vacation|holiday))?$",
    re.IGNORECASE,
)

# Inline duration pattern for searching within text (no anchors)
# Note: Longer alternatives listed first to ensure proper match (days before day)
INLINE_DURATION_PATTERN = re.compile(
    r"(?:for\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(days|day|nights|night|weeks|week)",
    re.IGNORECASE,
)

# Word-to-number mapping for duration parsing
WORD_TO_NUMBER: Dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


# =============================================================================
# 7. DESTINATION PATTERNS
# =============================================================================

# Origin prefix pattern (e.g., "from London", "leaving from NYC")
ORIGIN_PREFIX_PATTERN = re.compile(
    r"^(from|leaving\s+from|departing\s+from|flying\s+from|starting\s+from)\s+(.+)$",
    re.IGNORECASE,
)

# Origin location pattern for inline extraction (e.g., "based in London", "I'm from NYC")
ORIGIN_LOCATION_PATTERN = re.compile(
    r"(?:based\s+in|living\s+in|located\s+in|coming\s+from|residing\s+in|"
    r"i(?:'?m|\s+am)\s+(?:from|in))\s+(.+?)(?:[.,]|$)",
    re.IGNORECASE,
)

# Initial destination pattern (e.g., "I want to go to Paris")
INITIAL_DESTINATION_PATTERN = re.compile(
    r"(?:i\s+want\s+to\s+(?:go\s+to|visit|travel\s+to|fly\s+to)|"
    r"(?:trip|vacation|holiday)\s+to|"
    r"planning\s+(?:a\s+)?(?:trip|vacation|holiday)\s+to|"
    r"going\s+to|"
    r"(?:fly(?:ing)?|flights?)\s+to|"  # fly to, flying to, flight to
    r"(?:book(?:ing)?)\s+(?:a\s+)?(?:flight|flights)\s+to|"  # book a flight to
    r"let'?s\s+(?:go|fly)\s+to)\s+(.+?)"
    r"(?:\s+(?:from|next|in|for|with|tomorrow|today|direct|one[- ]?way|round[- ]?trip)\b"
    r"|[.!?,]|$)",
    re.IGNORECASE,
)

# Origin-destination pattern (e.g., "from London to Paris")
# The destination capture excludes trailing date/time words like "tomorrow",
# "today", etc. and numbers (e.g., "2 days") to avoid capturing
# "Amsterdam tomorrow" or "Amsterdam 2" as a destination.
_DATE_STOP_WORDS = (
    r"tomorrow|today|tonight|next|this|on|in|for|with|direct|nonstop|one[- ]?way|round[- ]?trip|\d"
)
ORIGIN_DESTINATION_PATTERN = re.compile(
    rf"(?:from\s+)?(\w+(?:\s+\w+)?)\s+to\s+(\w+(?:\s+(?!{_DATE_STOP_WORDS})\w+)?)",
    re.IGNORECASE,
)

# Multi-field simple input pattern
MULTI_FIELD_PATTERN = re.compile(
    r"^(?:(\d+)\s*(?:adult|people|person|traveler)s?(?:\s*,\s*|\s+and\s+|\s+)?)?"
    r"(\w+(?:\s+\w+)?)?(?:\s*,\s*|\s+)?"
    r"(next\s+(?:week|month)|in\s+\w+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*"
    r"(?:\s+\d+)?)?",
    re.IGNORECASE,
)


# =============================================================================
# 8. FLIGHT PATTERNS (NEW - Enhanced)
# =============================================================================

# Cabin class patterns
CABIN_CLASS_PATTERN = re.compile(
    r"\b(economy|premium\s+economy|business|first\s+class|first)\b",
    re.IGNORECASE,
)

# Direct/non-stop flight preference
DIRECT_FLIGHT_PATTERN = re.compile(
    r"\b(direct|non[- ]?stop|nonstop|no\s+stops?|no\s+layovers?)\b",
    re.IGNORECASE,
)

# Layover preferences
LAYOVER_PATTERN = re.compile(
    r"(?:"
    r"\b(no\s+layovers?|avoid\s+layovers?|without\s+layovers?)\b|"
    r"\b(short\s+layover|minimal\s+layover|quick\s+connection)\b|"
    r"\b(ok\s+with\s+layover|layover\s+(?:is\s+)?(?:ok|fine|acceptable))\b|"
    r"\b(max(?:imum)?\s+)?(\d+)\s*(?:hour|hr)s?\s*layover\b|"
    r"\blayover\s+(?:under|less\s+than|no\s+more\s+than)\s+(\d+)\s*(?:hour|hr)s?\b"
    r")",
    re.IGNORECASE,
)

# One-way vs round-trip
TRIP_TYPE_PATTERN = re.compile(
    r"\b(one[- ]?way|single|round[- ]?trip|return|open[- ]?jaw)\b",
    re.IGNORECASE,
)

# Airline preference patterns
AIRLINE_PREFERENCE_PATTERN = re.compile(
    r"(?:"
    # Specific airlines - major carriers
    r"\b(united|delta|american|southwest|jetblue|alaska|spirit|frontier|"
    r"lufthansa|british\s+airways|air\s+france|klm|emirates|qatar|singapore|"
    r"cathay\s+pacific|ana|jal|qantas|virgin|ryanair|easyjet|norwegian)\b|"
    # Generic airline preferences
    r"\b(avoid|prefer|only)\s+(\w+)\s*(?:airlines?|flights?|carriers?)\b|"
    # Alliance preferences
    r"\b(star\s+alliance|oneworld|skyteam)\b" r")",
    re.IGNORECASE,
)

# Time preference patterns
FLIGHT_TIME_PATTERN = re.compile(
    r"(?:"
    r"\b(morning|afternoon|evening|night|red[- ]?eye|overnight)\s+(?:flight|departure)\b|"
    r"\b(?:depart(?:ing)?|leave)\s+(?:in\s+the\s+)?(morning|afternoon|evening|night)\b|"
    r"\b(early|late)\s+(?:morning|afternoon|evening|night)?\s*(?:flight|departure)?\b|"
    r"\b(?:no|avoid)\s+(red[- ]?eye|overnight|night)\s*(?:flights?)?\b"
    r")",
    re.IGNORECASE,
)

# Baggage patterns
BAGGAGE_PATTERN = re.compile(
    r"(?:"
    r"\b(carry[- ]?on\s+only|no\s+checked\s+bags?|just\s+carry[- ]?on)\b|"
    r"\b(\d+)\s*checked\s+bags?\b|"
    r"\bwith\s+(checked\s+)?luggage\b|"
    r"\bincluded?\s+baggage\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 9. HOTEL PATTERNS (NEW - Enhanced)
# =============================================================================

# Star rating patterns
HOTEL_STAR_PATTERN = re.compile(
    r"(?:"
    r"\b(\d)\s*[- ]?\s*stars?\b|"  # "4 star", "4-star", "4 stars"
    r"\bstars?\s*:\s*(\d)\b|"  # "star: 4", "stars: 4"
    r"\bat\s+least\s+(\d)\s*stars?\b|"  # "at least 4 stars"
    r"\bminimum\s+(\d)\s*stars?\b|"  # "minimum 4 stars"
    r"\b(\d)\+\s*stars?\b"  # "4+ stars"
    r")",
    re.IGNORECASE,
)

# Hotel type patterns
HOTEL_TYPE_PATTERN = re.compile(
    r"\b(hotel|resort|boutique\s+hotel|hostel|motel|b&b|bed\s+and\s+breakfast|"
    r"airbnb|vrbo|vacation\s+rental|apartment|villa|cabin|lodge|inn|guesthouse|"
    r"all[- ]?inclusive)\b",
    re.IGNORECASE,
)

# Hotel amenity patterns
HOTEL_AMENITY_PATTERN = re.compile(
    r"\b(pool|swimming\s+pool|spa|gym|fitness\s+center|"
    r"breakfast(?:\s+included)?|free\s+breakfast|"
    r"wifi|wi[- ]?fi|internet|"
    r"parking|free\s+parking|valet|"
    r"pet[- ]?friendly|pets\s+allowed|"
    r"kitchen|kitchenette|"
    r"balcony|terrace|ocean\s+view|sea\s+view|city\s+view|"
    r"room\s+service|concierge|"
    r"air\s+condition(?:ing)?|ac|"
    r"laundry|washer|dryer|"
    r"jacuzzi|hot\s+tub|sauna|"
    r"bar|restaurant|lounge|"
    r"business\s+center|meeting\s+rooms?)\b",
    re.IGNORECASE,
)

# Room preference patterns
ROOM_PREFERENCE_PATTERN = re.compile(
    r"(?:"
    r"\b(king|queen|double|twin|single)\s*(?:bed|room|size)?\b|"
    r"\b(suite|junior\s+suite|penthouse|deluxe|standard)\s*(?:room)?\b|"
    r"\b(private\s+bathroom|ensuite|shared\s+bathroom)\b|"
    r"\b(connecting\s+rooms?|adjoining\s+rooms?)\b|"
    r"\b(\d)\s*(?:bed)?rooms?\b"  # "2 bedrooms"
    r")",
    re.IGNORECASE,
)

# Location preference patterns
HOTEL_LOCATION_PATTERN = re.compile(
    r"(?:"
    r"\b(near|close\s+to|walking\s+distance|next\s+to)\s+(the\s+)?"
    r"(beach|downtown|city\s+center|airport|train\s+station|metro|"
    r"attractions|shopping|restaurants?)\b|"
    r"\b(central|downtown|beachfront|airport\s+hotel|waterfront)\b|"
    r"\b(quiet|secluded|peaceful)\s+(?:location|area|neighborhood)?\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 10. TRANSPORT PATTERNS (NEW - Enhanced)
# =============================================================================

# Car rental patterns
CAR_RENTAL_PATTERN = re.compile(
    r"(?:"
    r"\b(rent\s+a?\s*car|car\s+rental|hire\s+(?:a\s+)?car|rental\s+car|renting\s+a\s+car)\b|"
    r"\b(need|want|prefer)\s+(?:a\s+)?(?:rental\s+)?car\b|"
    r"\b(driving|drive)\s+(?:around|there|myself)\b|"
    r"\b(suv|sedan|compact|economy\s+car|convertible|minivan|van)\s*(?:rental)?\b"
    r")",
    re.IGNORECASE,
)

# Train patterns
TRAIN_PATTERN = re.compile(
    r"(?:"
    r"\b(by\s+train|take\s+(?:the\s+)?train|train\s+(?:travel|journey|ride))\b|"
    r"\b(high[- ]?speed\s+train|bullet\s+train|express\s+train)\b|"
    r"\b(eurail|rail\s+pass|train\s+pass)\b|"
    r"\b(first\s+class|second\s+class|business\s+class)\s+(?:train|rail)\b|"
    r"\b(sleeper\s+train|overnight\s+train)\b"
    r")",
    re.IGNORECASE,
)

# Bus patterns
BUS_PATTERN = re.compile(
    r"(?:"
    r"\b(by\s+bus|take\s+(?:the\s+)?bus|bus\s+(?:travel|journey|ride))\b|"
    r"\b(coach|long[- ]?distance\s+bus|intercity\s+bus)\b|"
    r"\b(greyhound|flixbus|megabus)\b"
    r")",
    re.IGNORECASE,
)

# Ferry/boat patterns
FERRY_PATTERN = re.compile(
    r"(?:"
    r"\b(ferry|by\s+ferry|take\s+(?:the\s+)?ferry|boat\s+(?:ride|journey))\b|"
    r"\b(cruise|cruising)\b|"
    r"\b(catamaran|hydrofoil|water\s+taxi)\b"
    r")",
    re.IGNORECASE,
)

# Taxi/rideshare patterns
TAXI_PATTERN = re.compile(
    r"(?:"
    r"\b(taxi|cab|uber|lyft|grab|bolt|rideshare)\b|"
    r"\b(private\s+transfer|airport\s+transfer|shuttle)\b|"
    r"\b(private\s+driver|chauffeur)\b"
    r")",
    re.IGNORECASE,
)

# Public transit patterns
PUBLIC_TRANSIT_PATTERN = re.compile(
    r"(?:"
    r"\b(metro|subway|underground|tube)\b|"
    r"\b(public\s+transit|public\s+transport(?:ation)?)\b|"
    r"\b(tram|streetcar|light\s+rail)\b|"
    r"\b(city\s+pass|transit\s+pass|day\s+pass)\b"
    r")",
    re.IGNORECASE,
)

# Walking/biking patterns
WALKING_BIKING_PATTERN = re.compile(
    r"(?:"
    r"\b(walk(?:ing)?|on\s+foot|walkable)\b|"
    r"\b(bike|bicycle|cycling|rent\s+(?:a\s+)?bike|bike\s+rental)\b|"
    r"\b(e[- ]?bike|electric\s+(?:bike|scooter)|scooter)\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 11. ACTIVITY PATTERNS (NEW - Enhanced)
# =============================================================================

# Tour patterns
TOUR_PATTERN = re.compile(
    r"(?:"
    r"\b(guided\s+tour|walking\s+tour|bus\s+tour|food\s+tour|"
    r"wine\s+tour|pub\s+crawl|bike\s+tour)\b|"
    r"\b(day\s+trip|excursion|half[- ]?day\s+tour|full[- ]?day\s+tour)\b|"
    r"\b(private\s+tour|group\s+tour|self[- ]?guided)\b|"
    r"\b(sightseeing|city\s+tour)\b"
    r")",
    re.IGNORECASE,
)

# Museum/cultural patterns
MUSEUM_PATTERN = re.compile(
    r"(?:"
    r"\b(museum|gallery|art\s+museum|history\s+museum|science\s+museum)\b|"
    r"\b(exhibition|exhibit)\b|"
    r"\b(cultural\s+sites?|heritage\s+sites?|unesco)\b|"
    r"\b(castle|palace|cathedral|church|temple|mosque|synagogue)\b"
    r")",
    re.IGNORECASE,
)

# Outdoor activity patterns
OUTDOOR_ACTIVITY_PATTERN = re.compile(
    r"(?:"
    r"\b(hiking|trekking|trail|nature\s+walk)\b|"
    r"\b(snorkeling|diving|scuba|swimming)\b|"
    r"\b(surfing|kayaking|canoeing|paddleboarding|jet\s+ski)\b|"
    r"\b(zip[- ]?line|bungee|paragliding|skydiving)\b|"
    r"\b(rock\s+climbing|bouldering|rappelling)\b|"
    r"\b(skiing|snowboarding|sledding|ice\s+skating)\b|"
    r"\b(horseback\s+riding|atv|quad\s+biking)\b|"
    r"\b(fishing|whale\s+watching|bird\s+watching|safari)\b"
    r")",
    re.IGNORECASE,
)

# Relaxation/wellness patterns
WELLNESS_PATTERN = re.compile(
    r"(?:"
    r"\b(spa|massage|wellness|relax(?:ation)?)\b|"
    r"\b(yoga|meditation|retreat)\b|"
    r"\b(beach\s+day|pool\s+day|sunbathing)\b|"
    r"\b(thermal\s+bath|hot\s+springs?|onsen)\b"
    r")",
    re.IGNORECASE,
)

# Food/dining patterns
FOOD_PATTERN = re.compile(
    r"(?:"
    r"\b(restaurant|dining|fine\s+dining|local\s+food|street\s+food)\b|"
    r"\b(food\s+market|farmers?\s+market|night\s+market)\b|"
    r"\b(cooking\s+class|food\s+tour|wine\s+tasting|brewery|winery)\b|"
    r"\b(michelin|rooftop\s+bar|cocktail\s+bar)\b|"
    r"\b(vegetarian|vegan|gluten[- ]?free|halal|kosher)\b"
    r")",
    re.IGNORECASE,
)

# Entertainment/nightlife patterns
ENTERTAINMENT_PATTERN = re.compile(
    r"(?:"
    r"\b(nightlife|club(?:bing)?|bar|pub|live\s+music)\b|"
    r"\b(show|theater|theatre|concert|performance|opera|ballet)\b|"
    r"\b(sports?\s+game|football|soccer|basketball|baseball)\b|"
    r"\b(casino|amusement\s+park|theme\s+park|waterpark)\b|"
    r"\b(shopping|mall|boutique|outlet)\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 11a. ACCESSIBILITY & SPECIAL NEEDS PATTERNS
# =============================================================================

# Accessibility patterns
ACCESSIBILITY_PATTERN = re.compile(
    r"(?:"
    # Mobility needs
    r"\b(wheelchair|wheelchairs?)\s*(?:accessible|access|friendly)?\b|"
    r"\b(wheelchair\s+)?(?:accessible|accessibility)\b|"
    r"\b(mobility\s+(?:impaired|issues?|challenges?|needs?))\b|"
    r"\b(disabled\s+access|disability\s+access|handicap(?:ped)?\s+accessible)\b|"
    r"\b(walking\s+difficulties?|limited\s+mobility|mobility\s+aid)\b|"
    r"\b(walker|cane|crutches|mobility\s+scooter)\b|"
    # Visual/hearing
    r"\b(blind|visually\s+impaired|low\s+vision)\b|"
    r"\b(deaf|hearing\s+impaired|hard\s+of\s+hearing)\b|"
    # General accessibility
    r"\b(ada\s+compliant|barrier[- ]?free)\b|"
    r"\b(accessible\s+(?:room|bathroom|shower|entrance|transport))\b|"
    r"\b(step[- ]?free|no\s+stairs|elevator\s+access|ground\s+floor)\b|"
    r"\b(special\s+needs?|special\s+assistance|extra\s+assistance)\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 11b. PET TRAVEL PATTERNS
# =============================================================================

# Pet travel patterns
PET_TRAVEL_PATTERN = re.compile(
    r"(?:"
    # General pet mentions
    r"\b(travel(?:ing)?|go(?:ing)?|fly(?:ing)?)\s+with\s+(?:my\s+|our\s+|a\s+)?"
    r"(dog|cat|pet)s?\b|"
    r"\b(?:my\s+|our\s+)?(dog|cat|pet)s?\s+(?:is\s+)?(?:coming|traveling|flying)\b|"
    r"\b(bring(?:ing)?)\s+(?:my\s+|our\s+|the\s+)?(dog|cat|pet)s?\b|"
    # Pet-friendly requirements
    r"\b(pet[- ]?friendly|dog[- ]?friendly|cat[- ]?friendly)\b|"
    r"\b(pets?\s+allowed|dogs?\s+allowed|cats?\s+allowed)\b|"
    r"\b(accept(?:s)?\s+pets?|welcome(?:s)?\s+pets?)\b|"
    # Specific pet types
    r"\b(with\s+(?:my\s+|our\s+)?(?:small|large|big)?\s*(?:dog|puppy|cat|kitten))\b|"
    r"\b(service\s+(?:dog|animal)|emotional\s+support\s+(?:animal|dog|cat))\b|"
    # Pet services
    r"\b(pet\s+(?:sitting|sitter|care|boarding|kennel))\b|"
    r"\b(dog\s+(?:park|beach|walking))\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 11c. DIETARY & ALLERGY PATTERNS
# =============================================================================

# Dietary patterns (trip-level, expanded from FOOD_PATTERN)
DIETARY_PATTERN = re.compile(
    r"(?:"
    # Diets
    r"\b(vegetarian|vegan|pescatarian|flexitarian)\b|"
    r"\b(plant[- ]?based|meat[- ]?free|dairy[- ]?free)\b|"
    r"\b(keto|paleo|low[- ]?carb|whole30)\b|"
    # Religious dietary laws
    r"\b(halal|kosher|jain)\b|"
    # Allergies and intolerances
    r"\b(gluten[- ]?free|celiac|coeliac)\b|"
    r"\b(nut[- ]?free|peanut[- ]?free|tree[- ]?nut\s+allergy)\b|"
    r"\b(lactose[- ]?(?:free|intolerant)|dairy\s+allergy)\b|"
    r"\b(shellfish\s+allergy|seafood\s+allergy|fish\s+allergy)\b|"
    r"\b(egg[- ]?free|egg\s+allergy|soy[- ]?free|soy\s+allergy)\b|"
    r"\b(food\s+allerg(?:y|ies)|allergic\s+to)\b|"
    # General requirements
    r"\b(dietary\s+(?:restrictions?|requirements?|needs?|preferences?))\b|"
    r"\b(special\s+diet|strict\s+diet)\b|"
    r"\b(can'?t\s+eat|don'?t\s+eat|avoid(?:ing)?)\s+\w+\b"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# 12. INFEASIBILITY PATTERNS
# =============================================================================

INFEASIBILITY_SIGNALS: Dict[str, Pattern] = {
    # Dates in the past (explicit correction language)
    "dates_past": re.compile(
        r"\b(yesterday|last\s+week|last\s+month|already\s+passed|already\s+gone|"
        r"was\s+supposed\s+to|should\s+have\s+been|missed\s+the\s+date)\b",
        re.IGNORECASE,
    ),
    # Skiing in summer (seasonal impossibility)
    "skiing_summer": re.compile(
        r"\bski(ing)?\b.*\b(june|july|august|summer)\b|"
        r"\b(june|july|august|summer)\b.*\bski(ing)?\b",
        re.IGNORECASE,
    ),
    # Beach in winter for northern destinations
    "beach_winter": re.compile(
        r"\bbeach\b.*\b(december|january|february|winter)\b.*"
        r"\b(norway|sweden|finland|iceland|alaska|canada)\b|"
        r"\b(norway|sweden|finland|iceland|alaska|canada)\b.*\bbeach\b.*"
        r"\b(december|january|february|winter)\b",
        re.IGNORECASE,
    ),
    # Beach in landlocked countries (geographic impossibility)
    "beach_landlocked": re.compile(
        r"\bbeach\b.*\b(switzerland|austria|czech|hungary|serbia|slovakia|"
        r"luxembourg|liechtenstein|andorra|vatican|san\s+marino|bolivia|paraguay|"
        r"mongolia|nepal|bhutan|laos|kazakhstan|uzbekistan|turkmenistan|kyrgyzstan|"
        r"tajikistan|afghanistan|rwanda|burundi|uganda|zambia|zimbabwe|botswana|"
        r"malawi|lesotho|eswatini|ethiopia|chad|niger|mali|burkina\s+faso|"
        r"central\s+african|south\s+sudan)\b|"
        r"\b(switzerland|austria|czech|hungary|serbia|slovakia|luxembourg|"
        r"liechtenstein|andorra|bolivia|paraguay|mongolia|nepal|bhutan)\b.*\bbeach\b",
        re.IGNORECASE,
    ),
    # Impossible same-day intercontinental
    "same_day_impossible": re.compile(
        r"\bsame\s+day\b.*\b(tokyo|sydney|australia|japan|new\s+zealand)\b.*"
        r"\b(london|paris|new\s+york|europe|america)\b|"
        r"\b(london|paris|new\s+york|europe|america)\b.*\bsame\s+day\b.*"
        r"\b(tokyo|sydney|australia|japan|new\s+zealand)\b",
        re.IGNORECASE,
    ),
    # Explicit correction language from user
    "explicit_correction": re.compile(
        r"\b(that's\s+wrong|that's\s+incorrect|you\s+made\s+a\s+mistake|"
        r"fix\s+this|correct\s+this|change\s+this|that\s+won't\s+work|"
        r"not\s+possible|impossible|can't\s+do\s+that|won't\s+work)\b",
        re.IGNORECASE,
    ),
}


# =============================================================================
# 13. LQA (Last Question Answer) PATTERNS
# =============================================================================
# Patterns for detecting when user is answering the last asked question

# Multi-intent or correction signals that need full extraction (bail from LQA)
LQA_BAIL_PATTERNS: List[Pattern] = [
    re.compile(r"\b(also|and\s+book|plus|as\s+well)\b", re.IGNORECASE),  # Multi-intent
    re.compile(r"[,;].*[,;]", re.IGNORECASE),  # Multiple delimiters
    re.compile(r"\b(not|instead|change|actually|but)\b", re.IGNORECASE),  # Negation/correction
]

# =============================================================================
# P4.1: NEGATION ALTERNATIVE PATTERNS
# =============================================================================
# These patterns extract alternatives from negation expressions like "not X, maybe Y"
# Used in lqa_prepass to parse alternatives instead of bailing to LLM

# Pattern to extract alternatives from negation phrases
NEGATION_ALTERNATIVE_PATTERN: Pattern = re.compile(
    r"(?:"
    # "not Paris, maybe Barcelona"
    r"\bnot\s+[\w\s]+[,\-]\s*(?:maybe|try|how\s*about|instead)\s+(.+)|"
    r"\binstead\s+of\s+[\w\s]+[,\s]+(?:try\s+)?(.+)|"  # "instead of Rome, try Venice"
    r"\bnot\s+([\w\s]+)\s*(?:,\s*|\s+)but\s+(.+)|"  # "not Paris, but Barcelona"
    r"\b(?:change|switch)\s+(?:from\s+[\w\s]+\s+)?to\s+(.+)|"  # "change to London"
    r"\bactually[,\s]+(.+)|"  # "actually Tokyo"
    r"^(.+?)\s+instead$"  # "Barcelona instead"
    r")",
    re.IGNORECASE,
)

# Simple negation without an alternative (just reject, ask again)
SIMPLE_NEGATION_PATTERN: Pattern = re.compile(
    r"^(?:no(?:\s+thanks?)?|not\s+(?:that|this)|(?:I\s+)?don'?t\s+want|never\s*mind)[\s\.\!\?]*$",
    re.IGNORECASE,
)


# =============================================================================
# P2.3: COMPOUND TRAVELERS+DATE PATTERNS
# =============================================================================
# These patterns match combined travelers and date expressions like:
# - "2 adults for next month"
# - "family of 4 in December"
# - "couple for next week"
# Used in _run_deterministic_pipeline to parse both fields in one pass

# Pattern for travelers-first compound: "2 adults for next month"
COMPOUND_TRAVELERS_DATE_PATTERN: Pattern = re.compile(
    r"^(?P<travelers>"
    r"(?:\d+\s*(?:adults?|people|persons?|travelers?))"
    r"|(?:just\s+me|solo|myself)"
    r"|(?:couple|a\s+couple)"
    r"|(?:family\s+of\s+\d+)"
    r"|(?:\d+\s+of\s+us)"
    r")"
    r"\s+(?:for|in|during)\s+"
    r"(?P<date>.+)$",
    re.IGNORECASE,
)

# Pattern for date-first compound: "next month for 2 adults"
COMPOUND_DATE_TRAVELERS_PATTERN: Pattern = re.compile(
    r"^(?P<date>"
    r"(?:next\s+(?:week|month|year))"
    r"|(?:this\s+(?:week|month|year))"
    r"|(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"(?:\s+\d{4})?"
    r")"
    r"\s+(?:for|with)\s+"
    r"(?P<travelers>"
    r"(?:\d+\s*(?:adults?|people|persons?|travelers?))"
    r"|(?:a\s+couple|couple)"
    r"|(?:family\s+of\s+\d+)"
    r"|(?:\d+\s+of\s+us)"
    r")$",
    re.IGNORECASE,
)

# Compound keywords to detect multi-field input before parsing
COMPOUND_KEYWORDS: FrozenSet[str] = frozenset({"for", "in", "during", "with"})


# =============================================================================
# DENSE INPUT KEYWORDS
# =============================================================================
# Keywords indicating dense input requiring full extraction

# Topic keywords - used for routing/strategy detection, NOT for triggering FULL extraction
TOPIC_KEYWORDS: FrozenSet[str] = frozenset(
    [
        # Strategy/activity topics
        "hiking",
        "diving",
        "skiing",
        "cycling",
        "boating",
        "snorkeling",
        "surfing",
        "climbing",
        "trekking",
        "safari",
        "cruise",
        # Trip style/intent
        "adventure",
        "relaxation",
        "beach",
        "mountain",
        "city break",
        "road trip",
        "honeymoon",
        "backpacking",
        "luxury",
        "budget-friendly",
    ]
)

# Settings keywords - concrete booking preferences that require FULL extraction mode
DENSE_INPUT_KEYWORDS: FrozenSet[str] = frozenset(
    [
        # Flight settings
        "direct",
        "nonstop",
        "non-stop",
        "business",
        "first class",
        "economy",
        "one-way",
        "round-trip",
        "round trip",
        "layover",
        "stopover",
        "cabin",
        # Hotel settings
        "star",
        "stars",
        "boutique",
        "resort",
        "hostel",
        "airbnb",
        "pool",
        "spa",
        "gym",
        "amenities",
        "breakfast",
        "wifi",
        "parking",
        # Transport settings
        "car rental",
        "rent a car",
        "train",
        "bus",
        "ferry",
        "taxi",
        "uber",
        "transfer",
        # Generic activity keywords (not strategy topics)
        "tour",
        "museum",
        # Accessibility/special needs
        "wheelchair",
        "accessible",
        "accessibility",
        "mobility",
        "disabled",
        "handicap",
        "special needs",
        # Pet travel
        "pet-friendly",
        "dog-friendly",
        "traveling with dog",
        "traveling with pet",
        "pets allowed",
        # Dietary/allergies
        "vegetarian",
        "vegan",
        "halal",
        "kosher",
        "gluten-free",
        "food allergy",
        "allergic",
        "dietary",
        # Trip occasions
        "bachelor party",
        "bachelorette",
        "honeymoon",
        "anniversary",
        "work trip",
        "business trip",
        "conference",
    ]
)

# Greeting words blocklist for title-case heuristic
GREETING_BLOCKLIST: FrozenSet[str] = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank",
        "please",
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "great",
        "perfect",
        "awesome",
        "cool",
        "nice",
        "good",
        "fine",
    }
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_traveler_detail_answer(text: str, question_target: str | None) -> bool:
    """
    Check if text is a traveler detail answer (kid ages, etc.) that should
    bypass multi-intent bail patterns.

    Returns True if the text matches traveler-detail patterns and the
    question_target is travelers-related.
    """
    if question_target not in ("travelers", "adults", "children", None):
        return False

    # Check for "kids ages 3, 6, 12" pattern
    if TRAVELER_DETAIL_PATTERN.search(text):
        return True

    # Check for just "3, 6, 12" or "ages 3, 6, 12"
    if TRAVELER_AGES_ONLY_PATTERN.match(text):
        return True

    return False


def is_text_date_compatible(text: str) -> bool:
    """
    Check if text looks like a date answer (Single Source of Truth).

    This is the canonical function for determining if user text is answering
    a dates question. It consolidates the logic from:
    - DATES_COMPATIBILITY_PATTERN
    - GateEvaluator.text_is_compatible_with_target (dates branch)
    - _is_date_like_text

    Args:
        text: User input text

    Returns:
        True if the text appears to be a date-related answer
    """
    if not text:
        return False

    text_lower = text.lower().strip()

    # Use the canonical pattern for most checks
    if DATES_COMPATIBILITY_PATTERN.search(text_lower):
        return True

    # Additional checks for date-like numbers (ordinals, date formats)
    # These are checked here rather than bloating the regex
    import re

    if re.search(r"\b(\d{1,2}[/.-]\d{1,2}|\d{4}|\d{1,2}(?:st|nd|rd|th))\b", text_lower):
        return True

    # Check for preposition + month patterns
    if re.search(
        r"\b(in|around|by|before|after)\s+"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|"
        r"october|november|december)\b",
        text_lower,
    ):
        return True

    return False


def text_is_compatible_with_target(text: str, question_target: str | None) -> bool:
    """
    Check if user text is compatible with the current question_target.

    This is a pure, deterministic, non-LLM function used for conservative
    topic-switch bypass decisions.

    Returns True if the text appears to answer the question_target.
    Returns True if question_target is None (no target to check against).
    """
    if not question_target:
        return True

    text_lower = text.lower().strip()
    target_lower = question_target.lower()

    if target_lower == "budget":
        return bool(BUDGET_COMPATIBILITY_PATTERN.search(text_lower))

    if target_lower in ("dates", "start_date", "end_date"):
        # Use the consolidated date compatibility check
        return is_text_date_compatible(text)

    if target_lower in ("travelers", "adults", "children"):
        return bool(TRAVELERS_COMPATIBILITY_PATTERN.search(text_lower))

    # For other targets, default to True (don't block)
    return True


def parse_duration_text(text: str) -> int | None:
    """
    Parse duration text into number of days.

    Args:
        text: Text like "7 days", "one week", "10 nights"

    Returns:
        Number of days, or None if not parseable
    """
    match = DURATION_PATTERN.match(text.strip())
    if not match:
        return None

    num_str = match.group(1).lower()
    unit = match.group(2).lower()

    # Convert word to number if needed
    if num_str in WORD_TO_NUMBER:
        num = WORD_TO_NUMBER[num_str]
    else:
        try:
            num = int(num_str)
        except ValueError:
            return None

    # Convert to days
    if unit in ("week", "weeks"):
        return num * 7
    elif unit in ("day", "days", "night", "nights"):
        return num

    return None


def normalize_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def extract_hotel_stars(text: str) -> int | None:
    """
    Extract hotel star rating from text.

    Args:
        text: Text like "4 star hotel", "at least 3 stars"

    Returns:
        Star rating as int (1-5), or None if not found
    """
    match = HOTEL_STAR_PATTERN.search(text)
    if match:
        # Get the first non-None group
        for group in match.groups():
            if group:
                try:
                    stars = int(group)
                    if 1 <= stars <= 5:
                        return stars
                except ValueError:
                    pass
    return None


def extract_cabin_class(text: str) -> str | None:
    """
    Extract cabin class from text.

    Args:
        text: Text like "business class", "fly economy"

    Returns:
        Normalized cabin class (economy, premium_economy, business, first), or None
    """
    match = CABIN_CLASS_PATTERN.search(text)
    if match:
        cabin = match.group(1).lower()
        if cabin in ("first class", "first"):
            return "first"
        elif cabin == "premium economy":
            return "premium_economy"
        elif cabin == "business":
            return "business"
        elif cabin == "economy":
            return "economy"
    return None


def extract_hotel_amenities(text: str) -> List[str]:
    """
    Extract hotel amenities from text.

    Args:
        text: Text like "hotel with pool and spa"

    Returns:
        List of amenity strings found
    """
    amenities = []
    for match in HOTEL_AMENITY_PATTERN.finditer(text):
        amenity = match.group(0).lower().strip()
        if amenity not in amenities:
            amenities.append(amenity)
    return amenities


def is_direct_flight_preferred(text: str) -> bool:
    """Check if user prefers direct/non-stop flights."""
    return bool(DIRECT_FLIGHT_PATTERN.search(text))


def extract_trip_type(text: str) -> str | None:
    """
    Extract trip type (one-way or round-trip) from text.

    Returns:
        "one_way", "round_trip", or None
    """
    match = TRIP_TYPE_PATTERN.search(text)
    if match:
        trip_type = match.group(1).lower().replace("-", "").replace(" ", "")
        if trip_type in ("oneway", "single"):
            return "one_way"
        elif trip_type in ("roundtrip", "return"):
            return "round_trip"
    return None


def has_car_rental_intent(text: str) -> bool:
    """Check if user wants car rental."""
    return bool(CAR_RENTAL_PATTERN.search(text))


def has_train_intent(text: str) -> bool:
    """Check if user wants train travel."""
    return bool(TRAIN_PATTERN.search(text))


def has_accessibility_needs(text: str) -> bool:
    """Check if user has accessibility/special needs requirements."""
    return bool(ACCESSIBILITY_PATTERN.search(text))


def has_pet_travel(text: str) -> bool:
    """Check if user is traveling with pets."""
    return bool(PET_TRAVEL_PATTERN.search(text))


def extract_dietary_requirements(text: str) -> List[str]:
    """
    Extract dietary requirements/allergies from text.

    Args:
        text: Text like "I'm vegetarian and gluten-free"

    Returns:
        List of dietary requirement strings found
    """
    requirements = []
    for match in DIETARY_PATTERN.finditer(text):
        req = match.group(0).lower().strip()
        if req not in requirements:
            requirements.append(req)
    return requirements


def extract_trip_occasion(text: str) -> str | None:
    """
    Extract trip occasion/type from text.

    Args:
        text: Text like "planning a bachelor party trip"

    Returns:
        Trip occasion type, or None if not found
    """
    match = TRIP_OCCASION_PATTERN.search(text)
    if match:
        # Return the first non-None captured group
        for group in match.groups():
            if group:
                return group.lower().strip()
    return None


def has_flexible_dates(text: str) -> bool:
    """Check if user has flexible/open dates."""
    return bool(FLEXIBLE_DATES_PATTERN.search(text))


def extract_date_range(text: str) -> tuple[int | None, int | None, str | None]:
    """
    Extract date range from text.

    Args:
        text: Text like "Dec 15-22" or "15th to 22nd December"

    Returns:
        Tuple of (start_day, end_day, month) or (None, None, None) if not found
    """
    match = DATE_RANGE_PATTERN.search(text)
    if not match:
        return None, None, None

    groups = match.groups()
    # Different capture group positions depending on which pattern matched
    # Pattern 1: month day-day (groups 0,1,2)
    # Pattern 2: day-day month (groups 3,4,5)
    # Pattern 3: day to day month (groups 6,7,8)
    # Pattern 4: month day to day (groups 9,10,11)

    if groups[0]:  # "Dec 15-22"
        return int(groups[1]), int(groups[2]), groups[0].lower()
    elif groups[3]:  # "15-22 December"
        return int(groups[3]), int(groups[4]), groups[5].lower()
    elif groups[6]:  # "15th to 22nd December"
        return int(groups[6]), int(groups[7]), groups[8].lower()
    elif groups[9]:  # "December 15 to 22"
        return int(groups[10]), int(groups[11]), groups[9].lower()

    return None, None, None


def has_age_qualified_travelers(text: str) -> bool:
    """Check if user mentioned age-qualified travelers (infants, toddlers, seniors, etc.)."""
    return bool(AGE_QUALIFIED_PATTERN.search(text))


# =============================================================================
# 14. DATE PARSING PATTERNS (from plan_graph.py DateNormalizer)
# =============================================================================

# Month-to-month range pattern for detecting date-like input
# Matches: "June to November", "March through October", "Jan-Dec"
MONTH_TO_MONTH_RANGE_PATTERN = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s*(?:to|through|-|–|—)\s*"
    r"(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)$",
    re.IGNORECASE,
)

# Single month pattern: "November", "next June"
SINGLE_MONTH_PATTERN = re.compile(
    r"^(?:next\s+|this\s+)?(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)$",
    re.IGNORECASE,
)

# Ordinal suffix pattern: "15th", "1st", "22nd"
ORDINAL_SUFFIX_PATTERN = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)

# Partial date pattern: "December 2025", "Jan 2026"
PARTIAL_DATE_PATTERN = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})$",
    re.IGNORECASE,
)

# Month + day without year: "December 15", "Dec 15"
MONTH_DAY_PATTERN = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?$",
    re.IGNORECASE,
)

# ISO date format: "2025-12-28"
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Date range patterns: "December 20-27", "Dec 20-27", "20-27 December"
DATE_RANGE_WITH_YEAR_PATTERNS: List[Pattern] = [
    # "December 20-27" or "Dec 20-27" (optionally with year)
    re.compile(
        r"^(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?[-–—to\s]+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?$",
        re.IGNORECASE,
    ),
    # "20-27 December" or "20-27 Dec" (optionally with year)
    re.compile(
        r"^(\d{1,2})(?:st|nd|rd|th)?[-–—to\s]+(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s*(\d{4}))?$",
        re.IGNORECASE,
    ),
]

# Week of month pattern: "first week of January", "last week of December"
WEEK_OF_MONTH_PATTERN = re.compile(
    r"^(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+week\s+(?:of\s+)?"
    r"(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s*(\d{4}))?$",
    re.IGNORECASE,
)

# Explicit 4-digit year pattern
EXPLICIT_YEAR_PATTERN = re.compile(r"\b(20\d{2}|19\d{2})\b")

# Month-day extraction patterns (for use in normalize_extracted_dates)
MONTH_DAY_EXTRACTION_PATTERNS: List[Pattern] = [
    # "January 15, 2026" or "January 15 2026" or "January 15th, 2026"
    re.compile(
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+"
        r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
        re.IGNORECASE,
    ),
    # "15 January 2026" or "15th of January 2026"
    re.compile(
        r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:\s+of)?\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:,?\s+(\d{4}))?",
        re.IGNORECASE,
    ),
]


# =============================================================================
# 15. YEAR CLARIFICATION PATTERNS
# =============================================================================

# Year clarification patterns (for dates_clarify responses)
YEAR_CLARIFY_PATTERNS: List[Pattern] = [
    re.compile(
        r"this\s+(december|january|february|march|april|may|june|july|august|september|october|november)",
        re.IGNORECASE,
    ),
    re.compile(
        r"next\s+(december|january|february|march|april|may|june|july|august|september|october|november|year)",
        re.IGNORECASE,
    ),
    re.compile(r"(20\d{2})", re.IGNORECASE),  # Explicit year like "2025" or "2026"
    re.compile(r"this\s+year", re.IGNORECASE),
    re.compile(r"next\s+year", re.IGNORECASE),
]


# =============================================================================
# 16. USER INTENT ARCHETYPE PATTERNS
# =============================================================================

# Quick booking patterns - user wants streamlined, minimal questions
QUICK_BOOKING_PATTERNS: List[Pattern] = [
    re.compile(
        r"\b(just\s+flights?|book\s+now|asap|fastest|quick\s+book|just\s+need)\b", re.IGNORECASE
    ),
    re.compile(r"\b(hurry|urgent|immediately|right\s+away)\b", re.IGNORECASE),
]

# Short trip patterns - focus on essentials, compact itineraries
SHORT_TRIP_PATTERNS: List[Pattern] = [
    re.compile(
        r"\b(weekend|quick\s+trip|2-3\s+days|getaway|short\s+trip|day\s+trip)\b", re.IGNORECASE
    ),
    re.compile(r"\b(mini\s+vacation|long\s+weekend|brief\s+visit)\b", re.IGNORECASE),
]

# Adventurous patterns - hidden gems, off the beaten path
ADVENTUROUS_PATTERNS: List[Pattern] = [
    re.compile(
        r"\b(explore|off\s+the?\s+beaten\s+path|unique|adventure|hidden\s+gems?)\b", re.IGNORECASE
    ),
    re.compile(r"\b(authentic|local\s+experience|undiscovered|unusual)\b", re.IGNORECASE),
]

# Undecided patterns - user needs suggestions and guidance
UNDECIDED_PATTERNS: List[Pattern] = [
    re.compile(
        r"\b(not\s+sure|help\s+me|suggestions?|ideas?|recommend|where\s+should)\b", re.IGNORECASE
    ),
    re.compile(r"\b(can't\s+decide|options?|what\s+do\s+you\s+think)\b", re.IGNORECASE),
]


# =============================================================================
# 17. USER TONE PATTERNS
# =============================================================================

# Enthusiastic tone patterns
ENTHUSIASTIC_TONE_PATTERNS: List[Pattern] = [
    re.compile(r"!{2,}", re.IGNORECASE),  # Multiple exclamation marks
    re.compile(r"\b(can't\s+wait|so\s+excited|amazing|awesome|love\s+it|perfect)\b", re.IGNORECASE),
    re.compile(r"\b(yay|woohoo|fantastic|incredible|thrilled)\b", re.IGNORECASE),
]

# Frustrated tone patterns
FRUSTRATED_TONE_PATTERNS: List[Pattern] = [
    re.compile(r"\b(ugh|again\??|still|already\s+told|not\s+working)\b", re.IGNORECASE),
    re.compile(r"\b(confused|frustrat|annoying|wrong|doesn't\s+work)\b", re.IGNORECASE),
]


# =============================================================================
# 18. STRATEGY TOPIC PATTERNS
# =============================================================================

# Strategy topic detection patterns - use word boundaries to avoid false positives
# e.g., "skippered" should not match "ski"
STRATEGY_TOPIC_PATTERNS: Dict[str, Pattern] = {
    "hiking": re.compile(r"\b(?:hik(?:e|ing)|trek(?:king)?)\b", re.IGNORECASE),
    "diving": re.compile(r"\b(?:div(?:e|ing)|scuba|snorkel(?:ing)?)\b", re.IGNORECASE),
    "skiing": re.compile(r"\b(?:ski(?:ing)?|snowboard(?:ing)?)\b", re.IGNORECASE),
    "cycling": re.compile(r"\b(?:cycl(?:e|ing)|bik(?:e|ing)|bicycle)\b", re.IGNORECASE),
    "boating": re.compile(r"\b(?:boat(?:ing)?|sail(?:ing)?|yacht(?:ing)?)\b", re.IGNORECASE),
}


# =============================================================================
# 19. STRATEGY BYPASS CONSTRAINT PATTERNS
# =============================================================================

# Date constraint pattern for strategy bypass detection
BYPASS_DATE_CONSTRAINT_PATTERN = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"next\s+(?:week|month|year)|this\s+(?:week|month|year)|"
    r"\d{1,2}[/-]\d{1,2}|\d{4})\b",
    re.IGNORECASE,
)

# Budget constraint pattern for strategy bypass detection
BYPASS_BUDGET_CONSTRAINT_PATTERN = re.compile(
    r"\$\d+|€\d+|£\d+|\d+\s*(?:dollars|euros|pounds|usd|eur|gbp)|budget\s+(?:is|of|\d)",
    re.IGNORECASE,
)

# Travelers constraint pattern for strategy bypass detection
BYPASS_TRAVELERS_CONSTRAINT_PATTERN = re.compile(
    r"\b(?:\d+\s*(?:adults?|people|persons?|travelers?|of\s+us)|"
    r"(?:just\s+)?me|solo|alone|couple|family)\b",
    re.IGNORECASE,
)

# Combined bypass constraint patterns dict
BYPASS_CONSTRAINT_PATTERNS: Dict[str, Pattern] = {
    "dates": BYPASS_DATE_CONSTRAINT_PATTERN,
    "budget": BYPASS_BUDGET_CONSTRAINT_PATTERN,
    "travelers": BYPASS_TRAVELERS_CONSTRAINT_PATTERN,
}


# =============================================================================
# 20. WEEK ORDINALS MAPPING
# =============================================================================

# Mapping from ordinal word to week number (1-indexed)
WEEK_ORDINALS: Dict[str, int] = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "last": -1,  # Special: last week of month
}

# Today/tonight words for relative date detection
TODAY_WORDS: FrozenSet[str] = frozenset({"today", "tonight", "now"})


# =============================================================================
# 21. TOPIC SWITCH PATTERNS
# =============================================================================

# Override phrases that bypass topic switch cooldown
TOPIC_SWITCH_OVERRIDE_PHRASES: FrozenSet[str] = frozenset(
    {
        "actually",
        "instead",
        "switch to",
        "change to",
        "rather",
        "forget",
        "no wait",
    }
)

# Intent verb patterns that indicate topic switch request
TOPIC_SWITCH_INTENT_VERBS: FrozenSet[str] = frozenset(
    {
        "want",
        "wanna",
        "go",
        "do",
        "plan",
        "try",
        "include",
        "add",
        "also",
    }
)


# =============================================================================
# 22. QUESTION/DOMAIN KEYWORDS
# =============================================================================

# Question words for detecting question-word + domain keyword combos
QUESTION_WORDS: FrozenSet[str] = frozenset(
    {
        "what",
        "which",
        "how",
        "where",
        "when",
        "can",
        "could",
        "should",
        "do",
        "does",
        "are",
        "is",
    }
)

# Domain keywords for question-word combo detection
DOMAIN_KEYWORDS: Dict[str, FrozenSet[str]] = {
    "flights": frozenset({"flight", "flights", "flying", "fly", "airline", "airlines", "airport"}),
    "hotels": frozenset(
        {
            "hotel",
            "hotels",
            "stay",
            "accommodation",
            "lodging",
            "room",
            "rooms",
            "resort",
        }
    ),
    "transport": frozenset(
        {
            "transport",
            "train",
            "trains",
            "bus",
            "car rental",
            "rental car",
            "drive",
            "driving",
        }
    ),
    "activities": frozenset(
        {
            "activity",
            "activities",
            "things to do",
            "tour",
            "tours",
            "excursion",
            "sightseeing",
        }
    ),
}

# Specialist keywords for gate routing (unified definition)
# Used by: SpecialistPreCoreGate, ReadyNoFieldsGate, GateEvaluator
# Superset of all gate-specific keyword definitions
SPECIALIST_KEYWORDS: Dict[str, FrozenSet[str]] = {
    "flights": frozenset(
        {
            "flight",
            "flights",
            "fly",
            "flying",
            "airline",
            "airlines",
            "airport",
            "airfare",
            "plane",
            "direct flight",
            "nonstop",
            "layover",
            "layovers",  # plural form for word boundary matching
            "stopover",
            "stopovers",
            "connection",
            "connections",
        }
    ),
    "hotels": frozenset(
        {
            "hotel",
            "hotels",
            "hostel",
            "hostels",
            "boutique hotel",
            "accommodation",
            "lodging",
            "where to stay",
            # Note: "stay" alone is too broad - matches "during my stay" (duration)
            # Use "where to stay" or "place to stay" for accommodation intent
            "place to stay",
            "airbnb",
            "resort",
            "resorts",
            "motel",
            "guest house",
            "guesthouse",
            "bed and breakfast",
            "b&b",
        }
    ),
    "activities": frozenset(
        {
            "activities",
            "activity",
            "things to do",
            "what to do",
            "tour",
            "tours",
            "excursion",
            "excursions",
            "sightseeing",
            "attractions",
            "visit",
        }
    ),
    "transport": frozenset(
        {
            "transport",
            "transportation",
            "train",
            "trains",
            "bus",
            "buses",
            "car rental",
            "rental car",
            "rent a car",
            "drive",
            "driving",
            "taxi",
            "uber",
            "get around",
            "getting around",
        }
    ),
}


# =============================================================================
# 23. INTENT-ONLY KEYWORDS
# =============================================================================

# Intent-only keywords (for MVP fast path)
# These indicate user is expressing trip intent without concrete details
INTENT_ONLY_KEYWORDS: Dict[str, str] = {
    "adventure": "adventure",
    "hiking": "hiking",
    "outdoors": "adventure",
    "nature": "adventure",
    "beach": "beach",
    "relaxation": "relaxation",
    "skiing": "skiing",
    "snowboarding": "skiing",
    "diving": "diving",
    "snorkeling": "diving",
    "cycling": "cycling",
    "biking": "cycling",
    "boating": "boating",
    "sailing": "boating",
    "romantic": "romantic",
    "honeymoon": "romantic",
    "family": "family",
    "kids": "family",
    "cultural": "cultural",
    "historical": "cultural",
    "food": "culinary",
    "culinary": "culinary",
    "wine": "culinary",
    "luxury": "luxury",
    # NOTE: "budget" intentionally excluded to avoid collision with budget phrases
    "backpacking": "budget",
}


# =============================================================================
# 24. STRATEGY INTENT KEYWORDS
# =============================================================================

# Phrases indicating user wants only questions (bypass strategy_pre_core_value)
QUESTIONS_ONLY_PHRASES: FrozenSet[str] = frozenset(
    {
        "ask me questions",
        "what do you need from me",
        "what do you need to know",
        "what info do you need",
        "what information do you need",
        "need more info",
        "what else do you need",
        "just ask me",
        "go ahead and ask",
    }
)

# Strategy topics that qualify for pre-core value-first responses
STRATEGY_TOPICS: FrozenSet[str] = frozenset({"hiking", "skiing", "diving", "cycling", "boating"})

# Keywords that indicate strategy intent (broader than strict topic names)
STRATEGY_INTENT_KEYWORDS: Dict[str, FrozenSet[str]] = {
    "hiking": frozenset(
        {
            "hike",
            "hiking",
            "trek",
            "trekking",
            "trail",
            "trails",
            "mountain",
            "mountains",
        }
    ),
    # boating MUST come before skiing: "skippered" and "bareboat" contain "ski"
    "boating": frozenset(
        {
            "boat",
            "boating",
            "sail",
            "sailing",
            "yacht",
            "kayak",
            "canoe",
            "cruise",
            "skippered",
            "bareboat",
        }
    ),
    "skiing": frozenset({"skiing", "snowboard", "snowboarding", "slopes", "powder", "alpine"}),
    "diving": frozenset({"dive", "diving", "scuba", "snorkel", "snorkeling", "underwater"}),
    "cycling": frozenset({"bike", "biking", "bicycle", "cycling", "cycle", "ride", "pedal"}),
}


# =============================================================================
# 25. MULTI-CITY INTENT PHRASES
# =============================================================================

# Phrases indicating user wants separate trips for each destination
MULTI_CITY_SEPARATE_PHRASES: Tuple[str, ...] = (
    "separate trip",
    "separate trips",
    "do them separately",
    "different trips",
    "compare destinations",
    "compare them",
    "separate itinerary",
    "separate itineraries",
)

# Phrases indicating user wants a combined multi-city trip
MULTI_CITY_COMBINED_PHRASES: Tuple[str, ...] = (
    "multi city",
    "multicity",
    "one trip",
    "single trip",
    "same trip",
    "together",
    "all together",
    "one itinerary",
    "visit both",
    "visit all",
    "see both",
    "do both",
)

# Additive patterns that imply combining destinations (AND logic)
# These require checking the full phrase pattern, not just substring
ADDITIVE_INTENT_PATTERN = re.compile(
    r"\b(?:too|also|as\s+well|and\s+also)\b",
    re.IGNORECASE,
)


# =============================================================================
# 26. ENTITY DETECTION PATTERNS
# =============================================================================

# Combined pattern for detecting extractable entities in user text
# Used to determine if LLM extraction is needed vs intent-only fast path
ENTITY_DETECTION_PATTERN = re.compile(
    r"(?:"
    r"\d|"  # Numbers (dates, prices, travelers)
    r"[\$€£¥₹]|"  # Currency symbols
    # Month names (full and abbreviated)
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|"
    r"\b(?:next|this|last)\b|"  # Relative time
    r"\b(?:week|month|year)\b|"  # Time units
    r"\b(?:from|departing)\b"  # Origin indicators
    r")",
    re.IGNORECASE,
)
