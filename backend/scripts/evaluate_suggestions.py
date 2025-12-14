#!/usr/bin/env python3
"""Thorough evaluation of _is_low_quality_suggestion() function."""

# ruff: noqa: E402

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.plan_graph import _is_low_quality_suggestion

# Test cases organized by category
test_cases = {
    "VALID DESTINATIONS (should be ACCEPTED)": [
        "Nepal",
        "Bali",
        "Peru",
        "Iceland",
        "Norway",
        "Fiji",
        "Cuba",
        "Laos",
        "Oman",
        "Mali",
        "Paris, France",
        "Tokyo, Japan",
        "New York City",
        "Swiss Alps",
        "The Maldives",
        "Patagonia, Argentina",
        "Costa Rica",
        "New Zealand",
        "South Africa",
        "Rio de Janeiro",
        "Buenos Aires",
        "Hong Kong",
        "Sri Lanka",
    ],
    "VALID ORIGINS (should be ACCEPTED)": [
        "From London",
        "From NYC",
        "From Paris",
        "From Tokyo",
        "From Sydney",
        "New York",
        "Los Angeles",
        "San Francisco",
        "Chicago",
        "Boston",
    ],
    "VALID DATES (should be ACCEPTED)": [
        "Next month",
        "In 2 weeks",
        "December 28, 2025",
        "January 15, 2026",
        "December 15-22",
        "January 2026",
        "Next weekend",
        "Tomorrow",
        "In 3 days",
    ],
    "VALID TRAVELERS (should be ACCEPTED)": [
        "Just me",
        "2 adults",
        "Family of 4",
        "2 adults, 1 child",
        "Solo traveler",
        "Me and my partner",
        "Group of 6",
    ],
    "VALID BUDGET (should be ACCEPTED)": [
        "Around $2000",
        "Mid-range budget",
        "Luxury trip",
        "Budget friendly",
        "$5000 total",
        "Under $3000",
    ],
    "VALID ACTIVITIES (should be ACCEPTED)": [
        "Hiking and trekking",
        "Beach and relaxation",
        "Sightseeing and culture",
        "Food and wine tours",
        "Adventure activities",
        "Scuba diving",
    ],
    "VALID CONFIRMATIONS (should be ACCEPTED)": [
        "Looks good, generate my plan",
        "Ready to book",
        "That works for me",
        "Perfect, lets go",
        "Sounds great",
    ],
    "INVALID - Too short/vague (should be REJECTED)": [
        "ok",
        "hi",
        "no",
        "yes",
        "a",
        "go",
        "mm",
        "um",
    ],
    "INVALID - Assistant phrases (should be REJECTED)": [
        "I can help you with that",
        "Let me know if you need more",
        "Here are some options for you",
        "Feel free to ask",
        "I would be happy to assist you",
    ],
    "INVALID - Instruction style (should be REJECTED)": [
        "Add a destination",
        "Include beach activities",
        "Specify your dates",
        "Provide more details",
        "Enter your budget",
        "Select an option",
        "Choose a hotel",
        "Try exploring the area",
        "Find cheap flights",
    ],
    "INVALID - Vague patterns (should be REJECTED)": [
        "Something relaxing...",
        "Looking for [destination]",
        "Enter destination here",
        "Select your dates",
    ],
    "INVALID - Too generic (should be REJECTED)": [
        "Some options please",
        "More details needed",
        "A specific place",
        "The best destination",
        "Something nice",
        "Anything works",
    ],
    "INVALID - Too long (should be REJECTED)": [
        (
            "I would like to visit Paris France and also go to Rome Italy "
            "and maybe Barcelona Spain too"
        ),
    ],
    "EDGE CASES - Need review": [
        "NYC",
        "LA",
        "UK",
        "USA",
        "UAE",  # Short abbreviations
        "Go",
        "Try",
        "Set",  # Could be commands OR place names
        "Nice",
        "Split",
        "Reading",  # City names that are also common words
        "I",
        "A",
        "An",  # Single letters
        "2",
        "10",
        "2024",  # Numbers only
        "Beach",
        "Mountain",
        "City",  # Generic category words
        "First class",
        "Economy",  # Flight classes
        "Direct flights only",  # Preference
    ],
}


def main():
    print("=" * 80)
    print("THOROUGH EVALUATION OF _is_low_quality_suggestion()")
    print("=" * 80)

    issues_found = []
    edge_cases_review = []

    for category, cases in test_cases.items():
        print(f"\n{category}")
        print("-" * 60)

        for case in cases:
            is_rejected = _is_low_quality_suggestion(case)
            status = "REJECTED" if is_rejected else "ACCEPTED"

            # Check if result matches expectation
            if "should be ACCEPTED" in category and is_rejected:
                marker = "❌ WRONG"
                issues_found.append(f'"{case}": should be ACCEPTED but was REJECTED')
            elif "should be REJECTED" in category and not is_rejected:
                marker = "❌ WRONG"
                issues_found.append(f'"{case}": should be REJECTED but was ACCEPTED')
            elif "EDGE CASES" in category:
                marker = "⚠️ REVIEW"
                edge_cases_review.append(f'"{case}" -> {status}')
            else:
                marker = "✅ OK"

            print(f'  {marker} "{case}" -> {status}')

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if issues_found:
        print(f"\n❌ ISSUES FOUND: {len(issues_found)}")
        for issue in issues_found:
            print(f"   - {issue}")
    else:
        print("\n✅ All expected cases passed!")

    print(f"\n⚠️ EDGE CASES for manual review: {len(edge_cases_review)}")
    for ec in edge_cases_review:
        print(f"   - {ec}")

    # Return exit code based on issues
    return 1 if issues_found else 0


if __name__ == "__main__":
    sys.exit(main())
