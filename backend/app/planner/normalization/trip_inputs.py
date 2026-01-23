"""
Trip Input Normalization - Tier 3 Module Extraction.

This module contains the unified TripInputNormalizer class for normalizing
all trip inputs (dates, destinations, currency, travelers, settings).

Extracted from plan_graph.py for better organization and testability.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from app.debug_utils import _debug
from app.pattern_matching import ADDITIVE_INTENT_PATTERN
from app.planner.gates.constants import DateErrorCode
from app.planner.normalization.date import DateNormalizer, DateProvenance, normalize_str
from app.planner.normalization.types import NormalizationError

if TYPE_CHECKING:
    from app.plan_graph import TripInputs


# Type for stats update callback
StatsUpdater = Callable[[str, int], None]


class TripInputNormalizer:
    """
    Unified normalization for all trip inputs.

    Consolidates all normalization logic (dates, destinations, currency, travelers,
    settings) into a single class. This is the ONLY place where normalization
    should occur in the graph.

    Usage:
        normalizer = TripInputNormalizer()
        updates, errors = normalizer.normalize_all(trip_inputs, deltas)
    """

    # Extended currency symbol map (from graph_plan_utils.py - more complete)
    CURRENCY_SYMBOL_MAP: Dict[str, str] = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "₩": "KRW",
        "₽": "RUB",
        "₺": "TRY",
        "R$": "BRL",
        "kr": "SEK",
        "CHF": "CHF",
        "A$": "AUD",
        "C$": "CAD",
        "NZ$": "NZD",
        "HK$": "HKD",
        "S$": "SGD",
    }

    # Extended ISO-4217 currency codes (from graph_plan_utils.py - 30 currencies)
    SUPPORTED_CURRENCIES: frozenset = frozenset(
        {
            "USD",
            "EUR",
            "GBP",
            "CAD",
            "AUD",
            "JPY",
            "CHF",
            "CNY",
            "INR",
            "MXN",
            "BRL",
            "KRW",
            "SGD",
            "HKD",
            "NOK",
            "SEK",
            "DKK",
            "NZD",
            "ZAR",
            "RUB",
            "TRY",
            "PLN",
            "THB",
            "MYR",
            "IDR",
            "PHP",
            "CZK",
            "ILS",
            "AED",
            "SAR",
        }
    )

    def __init__(
        self,
        date_normalizer: Optional[DateNormalizer] = None,
        *,
        # Dependencies injected from plan_graph to avoid circular imports
        dest_exclude_words: Optional[frozenset] = None,
        deduplicate_destinations_fn: Optional[Callable[[List[str]], List[str]]] = None,
        deduplicate_activities_fn: Optional[Callable[[List[str]], List[str]]] = None,
        normalize_place_fn: Optional[Callable[[str], str]] = None,
        normalize_int_fn: Optional[Callable[[Any], Optional[int]]] = None,
        normalize_budget_fn: Optional[Callable[[Any], Optional[float]]] = None,
        normalize_booking_field_fn: Optional[Callable[[str, dict], Optional[dict]]] = None,
        normalize_multi_city_fn: Optional[Callable[[Any], Optional[str]]] = None,
        default_currency: str = "USD",
        default_booking_types: Optional[
            Dict[str, Any]
        ] = None,  # Tri-state: "off"|"suggested"|"on" or legacy bool
        update_stats_fn: Optional[StatsUpdater] = None,
    ):
        """
        Initialize with optional DateNormalizer instance and dependencies.

        Args:
            date_normalizer: DateNormalizer instance, creates new one if None.
            dest_exclude_words: Frozenset of words to exclude from destinations.
            deduplicate_destinations_fn: Function to deduplicate destinations.
            deduplicate_activities_fn: Function to deduplicate activities.
            normalize_place_fn: Function to normalize place names (fuzzy).
            normalize_int_fn: Function to normalize integers.
            normalize_budget_fn: Function to normalize budget values.
            normalize_booking_field_fn: Function to normalize booking fields.
            normalize_multi_city_fn: Function to normalize multi-city intent.
            default_currency: Default currency code.
            default_booking_types: Default booking types dict.
            update_stats_fn: Callback to update stats counters.
        """
        self._date_normalizer = date_normalizer or DateNormalizer()

        # Inject dependencies or use defaults
        self._dest_exclude_words = dest_exclude_words or frozenset()
        self._deduplicate_destinations = deduplicate_destinations_fn or (lambda x: x)
        self._deduplicate_activities = deduplicate_activities_fn or (lambda x: x)
        self._normalize_place = normalize_place_fn or (lambda x: x)
        self._normalize_int = normalize_int_fn or _default_normalize_int
        self._normalize_budget = normalize_budget_fn or _default_normalize_budget
        self._normalize_booking_field = normalize_booking_field_fn or (lambda k, v: v)
        self._normalize_multi_city = normalize_multi_city_fn or _default_normalize_multi_city
        self._default_currency = default_currency
        self._default_booking_types = default_booking_types or {
            "flights": True,
            "hotels": True,
            "transport": True,
            "activities": True,
        }
        self._update_stats = update_stats_fn

    def _increment_stat(self, key: str, amount: int = 1) -> None:
        """Increment a stats counter if callback is set."""
        if self._update_stats:
            self._update_stats(key, amount)

    # -------------------------------------------------------------------------
    # Date Normalization (delegates to DateNormalizer)
    # -------------------------------------------------------------------------
    def normalize_date(self, value: Any) -> Optional[str]:
        """Normalize date to ISO format (YYYY-MM-DD)."""
        return self._date_normalizer.normalize(value)

    def normalize_date_with_info(self, value: Any) -> tuple[Optional[str], bool]:
        """Normalize date, returning (iso_date, was_partial)."""
        return self._date_normalizer.normalize_with_info(value)

    def validate_date_range(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[str], List[NormalizationError], bool]:
        """
        Validate and fix date range issues with hardened invariants.

        Date Parsing Ownership Hierarchy:
        ---------------------------------
        1. LQA pre-pass (deterministic, zero-LLM) - first attempt
        2. FULL extractor (LLM-based) - fallback, authoritative output
        3. This method (normalizer) - invariant enforcement ONLY, no guessing

        Hardened Invariants:
        -------------------
        - NEVER store reversed dates (start_date > end_date)
        - If swap still produces invalid range, CLEAR both dates
        - Set date_clarify_mode when ambiguity detected

        Handles:
        - Cross-year correction (Dec start → Jan/Feb end)
        - Atomic date swap if end < start (with re-validation)
        - Past date warnings
        - Straddle-today ambiguity detection

        Returns:
            Tuple of (corrected_start, corrected_end, errors, needs_clarify)
            where needs_clarify=True triggers date_clarify_mode
        """
        errors: List[NormalizationError] = []
        corrected_start = start_date
        corrected_end = end_date
        needs_clarify = False

        if not start_date or not end_date:
            return corrected_start, corrected_end, errors, needs_clarify

        start_dt = self._date_normalizer.parse_iso(start_date)
        end_dt = self._date_normalizer.parse_iso(end_date)

        if not start_dt or not end_dt:
            return corrected_start, corrected_end, errors, needs_clarify

        today = self._date_normalizer.today

        # =====================================================================
        # PAST DATE HANDLING (moved up to run before straddle detection)
        # =====================================================================
        # If start_date is in the past, bump the entire range to next year.
        # This MUST run before straddle-today detection to avoid false ambiguity.
        if start_dt and start_dt.date() < today:
            # Bump past start dates to next year
            bumped_start_dt = start_dt.replace(year=start_dt.year + 1)
            corrected_start = bumped_start_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="start_date",
                    message=f"Start date {start_date} is in the past, bumped to {corrected_start}",
                    severity="warning",
                    original_value=start_date,
                )
            )
            _debug(f"Bumped past start date: {start_date} → {corrected_start}")

            # Also bump end date if it was in the same year
            if end_dt and end_dt.year == start_dt.year:
                bumped_end_dt = end_dt.replace(year=end_dt.year + 1)
                corrected_end = bumped_end_dt.strftime("%Y-%m-%d")
                _debug(f"Bumped end date to match: {end_date} → {corrected_end}")
                end_dt = bumped_end_dt

            start_dt = bumped_start_dt

        # =====================================================================
        # CROSS-YEAR CORRECTION (Dec start → Jan/Feb end)
        # =====================================================================
        if start_dt.month == 12 and end_dt.month in (1, 2) and end_dt.year == start_dt.year:
            corrected_end_dt = end_dt.replace(year=start_dt.year + 1)
            corrected_end = corrected_end_dt.strftime("%Y-%m-%d")
            errors.append(
                NormalizationError(
                    field="end_date",
                    message=f"Corrected cross-year date: {end_date} → {corrected_end}",
                    severity="warning",
                    original_value=end_date,
                )
            )
            _debug(f"Corrected cross-year date range: {end_date} → {corrected_end}")
            end_dt = corrected_end_dt

        # =====================================================================
        # ATOMIC DATE SWAP WITH RE-VALIDATION
        # =====================================================================
        # If end < start after corrections, attempt atomic swap
        if end_dt < start_dt:
            # Perform atomic swap
            swapped_start = corrected_end
            swapped_end = corrected_start
            corrected_start = swapped_start
            corrected_end = swapped_end

            errors.append(
                NormalizationError(
                    field="dates",
                    message=f"Swapped dates: start={start_date}, end={end_date}",
                    severity="warning",
                    original_value={"start_date": start_date, "end_date": end_date},
                )
            )
            _debug(f"Auto-swapped dates: {start_date} ↔ {end_date}")

            # Re-validate after swap
            swapped_start_dt = self._date_normalizer.parse_iso(corrected_start)
            swapped_end_dt = self._date_normalizer.parse_iso(corrected_end)

            if swapped_start_dt and swapped_end_dt and swapped_end_dt < swapped_start_dt:
                # Swap didn't fix it - clear both and require clarification
                self._increment_stat("date_range_invalid_count")
                errors.append(
                    NormalizationError(
                        field="dates",
                        code=DateErrorCode.RANGE_INVALID,
                        message=(
                            "Date range invalid after swap: " f"{corrected_start} > {corrected_end}"
                        ),
                        severity="blocking",
                        original_value={"start_date": start_date, "end_date": end_date},
                    )
                )
                if metadata is not None:
                    metadata["pending_date_range"] = {
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                needs_clarify = True
                _debug(
                    "🚫 DATE REJECTED: Range invalid after swap - user answer discarded",
                    user_provided_start=start_date,
                    user_provided_end=end_date,
                    rejection_reason="range_invalid_after_swap",
                )
                return None, None, errors, needs_clarify

            # Update datetime objects after successful swap
            start_dt = swapped_start_dt
            end_dt = swapped_end_dt

        # =====================================================================
        # FINAL INVARIANT CHECK
        # =====================================================================
        final_start_dt = self._date_normalizer.parse_iso(corrected_start)
        final_end_dt = self._date_normalizer.parse_iso(corrected_end)

        if final_start_dt and final_end_dt and final_end_dt < final_start_dt:
            # Still invalid after all corrections - this is a hard error
            self._increment_stat("date_range_invalid_count")
            errors.append(
                NormalizationError(
                    field="dates",
                    code=DateErrorCode.RANGE_INVALID,
                    message=f"Date range invariant violation: {corrected_start} > {corrected_end}",
                    severity="blocking",
                    original_value={"start_date": start_date, "end_date": end_date},
                )
            )
            if metadata is not None:
                metadata["pending_date_range"] = {
                    "start_date": start_date,
                    "end_date": end_date,
                }
            needs_clarify = True
            _debug(
                "🚫 DATE REJECTED: Final invariant check failed - user answer discarded",
                user_provided_start=start_date,
                user_provided_end=end_date,
                corrected_start=corrected_start,
                corrected_end=corrected_end,
                rejection_reason="invariant_violation",
            )
            # NEVER store reversed dates
            return None, None, errors, needs_clarify

        return corrected_start, corrected_end, errors, needs_clarify

    # -------------------------------------------------------------------------
    # Currency Normalization
    # -------------------------------------------------------------------------
    def normalize_currency(self, value: Any, *, default: Optional[str] = None) -> Optional[str]:
        """
        Normalize currency to ISO-4217 code.

        Maps symbols ($, €, £, etc.) to codes and validates against ISO-4217.
        Uses extended set of 30 currencies.
        """
        if value is None:
            return default

        text = normalize_str(value)
        if not text:
            return default

        # Check if it's a symbol
        if text in self.CURRENCY_SYMBOL_MAP:
            return self.CURRENCY_SYMBOL_MAP[text]

        # Uppercase and check against ISO codes
        code = text.upper()
        if code in self.SUPPORTED_CURRENCIES:
            return code

        # Check if symbol is part of value (e.g., "$100" -> extract $)
        for symbol, symbol_code in self.CURRENCY_SYMBOL_MAP.items():
            if text.startswith(symbol):
                return symbol_code

        return default

    # -------------------------------------------------------------------------
    # Traveler Normalization
    # -------------------------------------------------------------------------
    def clamp_travelers(self, value: Optional[int]) -> Optional[int]:
        """Constrain traveler count to valid range [0, 20]."""
        if value is None:
            return None
        return max(0, min(20, value))

    def normalize_adults(self, value: Any) -> Optional[int]:
        """Normalize adults count (min 1 when specified)."""
        int_val = self._normalize_int(value)
        if int_val is None:
            return None
        return max(1, min(20, int_val))

    def normalize_children(self, value: Any) -> Optional[int]:
        """Normalize children count (min 0)."""
        int_val = self._normalize_int(value)
        if int_val is None:
            return None
        return max(0, min(20, int_val))

    # -------------------------------------------------------------------------
    # Destination Normalization
    # -------------------------------------------------------------------------
    def normalize_destinations(
        self,
        destinations: List[str],
        new_destinations: Optional[List[str]] = None,
    ) -> tuple[List[str], List[NormalizationError]]:
        """
        Normalize and merge destinations.

        - Applies synonym mapping (NYC → New York City)
        - Filters phrase-like destinations containing excluded words
        - Deduplicates case-insensitively
        - Removes sublocations when parent exists

        Args:
            destinations: Existing destinations list
            new_destinations: New destinations to merge (optional)

        Returns:
            Tuple of (normalized_destinations, errors)
        """
        errors: List[NormalizationError] = []
        result = list(destinations)
        existing_lower = {d.lower() for d in result}

        if new_destinations:
            for d in new_destinations:
                d_norm = normalize_str(d)
                if not d_norm:
                    continue

                # Apply fuzzy normalization (handles synonyms + typos + casing)
                d_norm = self._normalize_place(d_norm)
                d_lower = d_norm.lower()

                # Filter phrase-like destinations
                if any(word in d_lower for word in self._dest_exclude_words):
                    errors.append(
                        NormalizationError(
                            field="destinations",
                            message=f"Filtered phrase-like destination: {d_norm}",
                            severity="warning",
                            original_value=d,
                        )
                    )
                    _debug(f"Filtering phrase-like destination: {d_norm}")
                    continue

                # Skip duplicates
                if d_lower not in existing_lower:
                    result.append(d_norm)
                    existing_lower.add(d_lower)

        # Deduplicate overlapping locations
        result = self._deduplicate_destinations(result)

        return result, errors

    # -------------------------------------------------------------------------
    # Settings Normalization
    # -------------------------------------------------------------------------
    def merge_nested_settings(
        self,
        existing: Optional[Dict[str, Any]],
        delta: Dict[str, Any],
        list_fields: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Merge nested settings dict with special handling for list fields.

        For list fields (like 'amenities'), extends rather than replaces.

        MUTATION PROTECTION (Tier 3): Creates copies of lists before extending
        to prevent shared reference mutations.
        """
        list_fields = list_fields or {"amenities", "categories"}
        result = dict(existing) if existing else {}

        for key, value in delta.items():
            if key in list_fields and isinstance(value, list):
                # MUTATION PROTECTION: Create a new list to avoid mutating original
                existing_list = list(result.get(key, []))  # Copy, don't reference
                for item in value:
                    if item not in existing_list:
                        existing_list.append(item)
                result[key] = existing_list
            else:
                result[key] = value

        return result

    # -------------------------------------------------------------------------
    # Full Normalization Pass
    # -------------------------------------------------------------------------
    def normalize_all(
        self,
        trip_inputs: "TripInputs",
        deltas: Dict[str, Any],
        user_text: Optional[str] = None,
    ) -> tuple[Dict[str, Any], List[NormalizationError]]:
        """
        Single normalization pass for all trip inputs.

        This is the ONLY place where normalization should occur.
        Called from normalize_inputs node.

        Args:
            trip_inputs: Current TripInputs state
            deltas: Dict of field deltas to apply (from extractor)
            user_text: Original user text, used to recover dates when LLM strips the day

        Returns:
            Tuple of (updates_dict, errors_list)
        """
        _debug("TripInputNormalizer.normalize_all called - single normalization pass")

        updates: Dict[str, Any] = {}
        errors: List[NormalizationError] = []
        # Track inputs that were provided but couldn't be normalized
        failed_inputs: List[Dict[str, Any]] = []

        # --- Origin ---
        if "origin_delta" in deltas:
            origin_raw = normalize_str(deltas["origin_delta"])
            if origin_raw:
                # Apply fuzzy normalization (handles synonyms + typos + casing)
                updates["origin"] = self._normalize_place(origin_raw)
            else:
                # User provided origin but it couldn't be normalized
                failed_inputs.append(
                    {
                        "field": "origin",
                        "raw_value": deltas["origin_delta"],
                        "reason": "Could not understand the departure city",
                        "user_message": (
                            f"I couldn't understand '{deltas['origin_delta']}' as a city. "
                            "Could you please specify your departure city?"
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: origin",
                    raw_value=deltas["origin_delta"],
                    reason="empty after normalization",
                )

        # --- Destinations ---
        if "destinations_delta" in deltas:
            dest_list = deltas["destinations_delta"]
            if isinstance(dest_list, str):
                dest_list = [dest_list]
            if isinstance(dest_list, list):
                normalized_dests, dest_errors = self.normalize_destinations(
                    trip_inputs.destinations, dest_list
                )
                if normalized_dests != trip_inputs.destinations:
                    updates["destinations"] = normalized_dests
                errors.extend(dest_errors)

        # --- Dates ---
        partial_date_notifications: List[str] = []
        # Track date provenance for explicit year protection
        date_provenance_updates: Dict[str, DateProvenance] = {}

        # Get current turn number for provenance tracking
        turn_number = deltas.get("_turn_number")

        # First, try to parse date ranges from start_date_hint (e.g., "December 20-27")
        # This handles cases where LLM sends the range as a single hint
        if "start_date_hint" in deltas and not trip_inputs.start_date:
            raw_hint = deltas["start_date_hint"]

            # Try parsing as a date range first
            range_start, range_end = self._date_normalizer.parse_date_range(raw_hint)
            if range_start and range_end:
                # Check for explicit year in the range hint
                explicit_year = self._date_normalizer.has_explicit_year(raw_hint)
                updates["start_date"] = range_start
                updates["end_date"] = range_end
                date_provenance_updates["start_date"] = DateProvenance(
                    value=range_start,
                    source_turn=turn_number,
                    explicit_year=explicit_year,
                    parsed_from="date_range",
                )
                date_provenance_updates["end_date"] = DateProvenance(
                    value=range_end,
                    source_turn=turn_number,
                    explicit_year=explicit_year,
                    parsed_from="date_range",
                )
                _debug(
                    "Parsed date range from start_date_hint",
                    raw=raw_hint,
                    start=range_start,
                    end=range_end,
                    explicit_year=explicit_year,
                )
            else:
                # Fall back to single date parsing with provenance tracking
                provenance = self._date_normalizer.normalize_with_provenance(raw_hint, turn_number)
                if provenance:
                    # If we got a partial_month result, try to recover full date from user_text
                    if provenance.parsed_from == "partial_month" and user_text:
                        # Extract month hint for targeted search
                        month_hint = raw_hint.split()[0] if raw_hint else None
                        full_date = self._date_normalizer.find_date_in_text(user_text, month_hint)
                        if full_date:
                            _debug(
                                "Recovered full date from user_text",
                                llm_hint=raw_hint,
                                recovered_date=full_date,
                                user_text=user_text[:50],
                            )
                            # Use the recovered date instead
                            explicit_year = self._date_normalizer.has_explicit_year(user_text)
                            provenance = DateProvenance(
                                value=full_date,
                                source_turn=turn_number,
                                explicit_year=explicit_year,
                                parsed_from="user_text_recovery",
                            )
                        else:
                            partial_date_notifications.append(
                                f"start_date set to first of month from '{raw_hint}'"
                            )
                    updates["start_date"] = provenance.value
                    date_provenance_updates["start_date"] = provenance
                else:
                    # Could not parse start_date_hint at all
                    failed_inputs.append(
                        {
                            "field": "start_date",
                            "raw_value": raw_hint,
                            "reason": "Could not parse as a valid date",
                            "user_message": (
                                f"I couldn't understand '{raw_hint}' as a date. "
                                "Could you please provide your travel dates "
                                "(e.g., 'January 15-22' or 'next month')?"
                            ),
                        }
                    )
                    _debug(
                        "🚫 USER INPUT FAILED: start_date",
                        raw_value=raw_hint,
                        reason="could not parse as valid date",
                    )

        if "end_date_hint" in deltas:
            raw_hint = deltas["end_date_hint"]
            provenance = self._date_normalizer.normalize_with_provenance(raw_hint, turn_number)
            if provenance:
                # If we got a partial_month result, try to recover full date from user_text
                if provenance.parsed_from == "partial_month" and user_text:
                    month_hint = raw_hint.split()[0] if raw_hint else None
                    # For end_date, we need to find a second date or a range end
                    full_date = self._date_normalizer.find_date_in_text(user_text, month_hint)
                    if full_date:
                        _debug(
                            "Recovered full end_date from user_text",
                            llm_hint=raw_hint,
                            recovered_date=full_date,
                        )
                        explicit_year = self._date_normalizer.has_explicit_year(user_text)
                        provenance = DateProvenance(
                            value=full_date,
                            source_turn=turn_number,
                            explicit_year=explicit_year,
                            parsed_from="user_text_recovery",
                        )
                    else:
                        partial_date_notifications.append(
                            f"end_date set to first of month from '{raw_hint}'"
                        )
                updates["end_date"] = provenance.value
                date_provenance_updates["end_date"] = provenance
            else:
                # Could not parse end_date_hint at all
                failed_inputs.append(
                    {
                        "field": "end_date",
                        "raw_value": raw_hint,
                        "reason": "Could not parse as a valid date",
                        "user_message": (
                            f"I couldn't understand '{raw_hint}' as an end date. "
                            "Could you please clarify when your trip ends?"
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: end_date",
                    raw_value=raw_hint,
                    reason="could not parse as valid date",
                )

        # Duration-based end_date computation
        if "duration_days_hint" in deltas and not trip_inputs.end_date:
            start = updates.get("start_date") or trip_inputs.start_date
            duration = self._normalize_int(deltas["duration_days_hint"])
            if start and duration and duration > 0:
                end = self._date_normalizer.compute_end_from_duration(start, duration)
                if end:
                    updates["end_date"] = end
                    updates["duration_days"] = duration

        # Validate date range (cross-year, swap, past-date)
        start = updates.get("start_date") or trip_inputs.start_date
        end = updates.get("end_date") or trip_inputs.end_date
        if start and end:
            corrected_start, corrected_end, date_errors, needs_clarify = self.validate_date_range(
                start, end
            )
            if corrected_start != start:
                updates["start_date"] = corrected_start
            if corrected_end != end:
                updates["end_date"] = corrected_end
            errors.extend(date_errors)
            if needs_clarify:
                updates["_needs_date_clarify"] = True
                # Store the user's rejected answer for reference in clarification prompts
                updates["_rejected_date_answer"] = {
                    "user_text": user_text,
                    "parsed_start": start,
                    "parsed_end": end,
                    "rejection_reasons": [
                        e.message for e in date_errors if e.severity == "blocking"
                    ],
                }
                _debug(
                    "🚫 USER DATE ANSWER REJECTED - stored for clarification",
                    user_text=user_text[:50] if user_text else None,
                    parsed_start=start,
                    parsed_end=end,
                    corrected_to=(corrected_start, corrected_end),
                    error_count=len([e for e in date_errors if e.severity == "blocking"]),
                )

        # Store partial date notifications in metadata
        if partial_date_notifications:
            updates["_partial_date_notifications"] = partial_date_notifications

        # --- Travelers ---
        if "adults_delta" in deltas:
            adults = self.normalize_adults(deltas["adults_delta"])
            if adults is not None:
                updates["adults"] = adults
            else:
                failed_inputs.append(
                    {
                        "field": "adults",
                        "raw_value": deltas["adults_delta"],
                        "reason": "Could not parse as a valid number of adults",
                        "user_message": (
                            f"I couldn't understand '{deltas['adults_delta']}' as a number of "
                            "travelers. How many adults will be traveling?"
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: adults",
                    raw_value=deltas["adults_delta"],
                    reason="could not parse as valid adult count",
                )

        if "children_delta" in deltas:
            children = self.normalize_children(deltas["children_delta"])
            if children is not None:
                updates["children"] = children
            else:
                failed_inputs.append(
                    {
                        "field": "children",
                        "raw_value": deltas["children_delta"],
                        "reason": "Could not parse as a valid number of children",
                        "user_message": (
                            f"I couldn't understand '{deltas['children_delta']}' as a number "
                            "of children. How many children will be joining?"
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: children",
                    raw_value=deltas["children_delta"],
                    reason="could not parse as valid children count",
                )

        if "requires_assistance_delta" in deltas:
            updates["requires_assistance"] = deltas["requires_assistance_delta"]

        # --- Budget & Currency ---
        if "budget_delta" in deltas:
            budget_raw = deltas["budget_delta"]
            budget = self._normalize_budget(budget_raw)
            if budget is not None:
                updates["budget"] = budget
                # Extract currency from dict format if present and not already provided
                if (
                    isinstance(budget_raw, dict)
                    and "currency" in budget_raw
                    and "currency_delta" not in deltas
                ):
                    currency = self.normalize_currency(budget_raw["currency"])
                    if currency:
                        updates["currency"] = currency
            else:
                failed_inputs.append(
                    {
                        "field": "budget",
                        "raw_value": budget_raw,
                        "reason": "Could not parse as a valid budget amount",
                        "user_message": (
                            f"I couldn't understand '{budget_raw}' as a budget. "
                            "Could you specify an amount (e.g., '$2000' or "
                            "'around 3000 euros')?"
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: budget",
                    raw_value=budget_raw,
                    reason="could not parse as valid budget amount",
                )

        if "currency_delta" in deltas:
            currency = self.normalize_currency(deltas["currency_delta"])
            if currency:
                updates["currency"] = currency
            else:
                failed_inputs.append(
                    {
                        "field": "currency",
                        "raw_value": deltas["currency_delta"],
                        "reason": "Could not recognize as a valid currency",
                        "user_message": (
                            f"I couldn't recognize '{deltas['currency_delta']}' as a currency. "
                            "Please use USD, EUR, GBP, or another standard currency code."
                        ),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: currency",
                    raw_value=deltas["currency_delta"],
                    reason="could not normalize to valid currency code",
                )
        elif "budget_delta" in deltas and not trip_inputs.currency:
            # Default currency if budget set but no currency
            updates["currency"] = self._default_currency

        # --- Multi-city Intent ---
        if "multi_city_intent_delta" in deltas:
            intent = self._normalize_multi_city(deltas["multi_city_intent_delta"])
            if intent:
                updates["multi_city_intent"] = intent
            else:
                failed_inputs.append(
                    {
                        "field": "multi_city_intent",
                        "raw_value": deltas["multi_city_intent_delta"],
                        "reason": "Could not understand trip type",
                        "user_message": ("Trip type unclear. " "Multi-city trip?"),
                    }
                )
                _debug(
                    "🚫 USER INPUT FAILED: multi_city_intent",
                    raw_value=deltas["multi_city_intent_delta"],
                    reason="could not normalize to valid multi-city intent",
                )

        # --- Settings (flight, hotel, transport, activity) ---
        if "flight_settings_delta" in deltas:
            delta = deltas["flight_settings_delta"]
            if isinstance(delta, dict):
                normalized = self._normalize_booking_field("flight_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.flight_settings, normalized)
                    updates["flight_settings"] = merged

        if "hotel_settings_delta" in deltas:
            delta = deltas["hotel_settings_delta"]
            if isinstance(delta, dict):
                normalized = self._normalize_booking_field("hotel_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(
                        trip_inputs.hotel_settings, normalized, list_fields={"amenities"}
                    )
                    updates["hotel_settings"] = merged

        if "transport_settings_delta" in deltas:
            delta = deltas["transport_settings_delta"]
            if isinstance(delta, dict):
                normalized = self._normalize_booking_field("transport_settings", delta)
                if normalized:
                    merged = self.merge_nested_settings(trip_inputs.transport_settings, normalized)
                    updates["transport_settings"] = merged

        if "activity_categories_delta" in deltas:
            delta = deltas["activity_categories_delta"]
            if isinstance(delta, list):
                existing = trip_inputs.activity_settings or {}
                existing_cats = list(existing.get("categories", []))
                # Normalize via _normalize_booking_field for consistency
                normalized = self._normalize_booking_field(
                    "activity_settings", {"categories": delta}
                )
                if normalized and "categories" in normalized:
                    for cat in normalized["categories"]:
                        if cat not in existing_cats:
                            existing_cats.append(cat)
                    # Deduplicate case-insensitively
                    existing_cats = self._deduplicate_activities(existing_cats)
                updates["activity_settings"] = {"categories": existing_cats}

        # --- Category Activation (booking types) ---
        if "category_activation" in deltas:
            activation = deltas["category_activation"]
            booking_types = dict(trip_inputs.booking_types or self._default_booking_types)

            if isinstance(activation, list):
                # Handle array format from extractor: ["flights", "hotels"]
                for cat in activation:
                    if cat in booking_types:
                        booking_types[cat] = True
                updates["booking_types"] = booking_types
            elif isinstance(activation, dict):
                # Handle dict format: {"flights": true, "hotels": true}
                # Also supports tri-state strings: "off", "suggested", "on"
                for cat, enabled in activation.items():
                    if cat in booking_types and (
                        isinstance(enabled, bool) or enabled in ("off", "suggested", "on")
                    ):
                        booking_types[cat] = enabled
                updates["booking_types"] = booking_types

        # --- Direct booking_types updates (from UI toggles) ---
        if "booking_types" in deltas:
            booking_types_delta = deltas["booking_types"]
            if isinstance(booking_types_delta, dict):
                booking_types = dict(trip_inputs.booking_types or self._default_booking_types)
                for cat, enabled in booking_types_delta.items():
                    # Accept both boolean (legacy) and tri-state strings
                    if cat in booking_types and (
                        isinstance(enabled, bool) or enabled in ("off", "suggested", "on")
                    ):
                        booking_types[cat] = enabled
                updates["booking_types"] = booking_types

        # --- Budget Per Night Derivation ---
        # Compute budget_per_night if we have budget_total and dates
        budget_total = updates.get("budget") or trip_inputs.budget
        start_date = updates.get("start_date") or trip_inputs.start_date
        end_date = updates.get("end_date") or trip_inputs.end_date

        if budget_total and start_date and end_date:
            # Only derive if not already explicitly set
            existing_budget_basis = (
                trip_inputs.strategy_settings.get("budget_basis")
                if trip_inputs.strategy_settings
                else None
            )
            if existing_budget_basis != "per_night":
                start_dt = self._date_normalizer.parse_iso(start_date)
                end_dt = self._date_normalizer.parse_iso(end_date)
                if start_dt and end_dt:
                    nights = max(1, (end_dt.date() - start_dt.date()).days)
                    budget_per_night = round(budget_total / nights, 2)

                    # Store in strategy_settings (extend existing or create new)
                    strategy_updates = dict(
                        updates.get("strategy_settings") or trip_inputs.strategy_settings or {}
                    )
                    strategy_updates["budget_per_night"] = budget_per_night
                    strategy_updates["budget_total"] = budget_total
                    strategy_updates["budget_nights"] = nights
                    if "budget_basis" not in strategy_updates:
                        strategy_updates["budget_basis"] = "total"
                    updates["strategy_settings"] = strategy_updates

                    _debug(
                        "Derived budget_per_night",
                        budget_total=budget_total,
                        nights=nights,
                        budget_per_night=budget_per_night,
                    )

        # --- Store Date Provenance for merge protection ---
        if date_provenance_updates:
            updates["_date_provenance"] = {
                k: v.to_dict() for k, v in date_provenance_updates.items()
            }

        # --- Flexible Dates Support ---
        # Pass through date_flex, trip_duration, date_window_* fields directly
        if "date_flex" in deltas:
            updates["date_flex"] = bool(deltas["date_flex"])
            _debug("Set date_flex", value=updates["date_flex"])
        if "trip_duration" in deltas:
            duration = self._normalize_int(deltas["trip_duration"])
            if duration and duration > 0:
                updates["trip_duration"] = duration
                _debug("Set trip_duration", value=duration)
        if "date_window_start" in deltas:
            updates["date_window_start"] = deltas["date_window_start"]
        if "date_window_end" in deltas:
            updates["date_window_end"] = deltas["date_window_end"]

        # --- Store failed inputs for user feedback ---
        if failed_inputs:
            updates["_failed_inputs"] = failed_inputs

        return updates, errors


# =============================================================================
# DEFAULT HELPER FUNCTIONS
# =============================================================================


def _default_normalize_int(value: Any) -> Optional[int]:
    """Convert any value to an integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(str(value).strip())
        except Exception:
            return None


def _default_normalize_budget(value: Any) -> Optional[float]:
    """Normalize a budget value to a float, handling currency symbols and dict format."""
    if value is None:
        return None

    # Handle dict format from LLM: {"budget": number, "currency": "USD"}
    if isinstance(value, dict):
        budget_value = value.get("budget")
        if budget_value is not None:
            return _default_normalize_budget(budget_value)  # Recurse to handle the inner value
        return None

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols and commas, extract number
        cleaned = re.sub(r"[^\d.]", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


def _default_normalize_multi_city(value: Any) -> Optional[str]:
    """
    Normalize multi-city intent from canonical values or natural language phrases.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return "multi_city" if value else "separate"

    text = normalize_str(value)
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("-", " ")).strip()

    # Quick exact matches
    if normalized in {
        "multi city",
        "multicity",
        "multi city trip",
        "multi city itinerary",
        "multi city intent",
    }:
        return "multi_city"
    if normalized in {
        "separate",
        "separate trip",
        "separate trips",
        "separate itinerary",
        "separate itineraries",
    }:
        return "separate"

    # Phrase-based inference using imported pattern
    if ADDITIVE_INTENT_PATTERN.search(normalized):
        return "multi_city"

    # Check for "separate" keywords
    if "not separate" not in normalized:
        for kw in ["separate", "compare", "different"]:
            if kw in normalized:
                return "separate"

    return None
