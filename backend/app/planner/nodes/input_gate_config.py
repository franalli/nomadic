"""Threshold constants for input gate validation. Single source of truth."""

GATE_THRESHOLDS = {
    # Dates
    "max_days_in_future": 548,  # ~18 months
    "max_trip_days": 90,
    "warn_trip_days": 30,
    "min_trip_days": 1,
    # Travelers
    "max_adults": 20,
    "max_children": 15,
    "max_total_travelers": 25,
    # Budget (USD-equivalent for MVP)
    "max_budget_usd": 500_000,
    "min_budget_usd": 50,
    "warn_budget_high_usd": 100_000,
}
