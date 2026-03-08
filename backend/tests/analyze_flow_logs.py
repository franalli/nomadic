#!/usr/bin/env python3
"""
Flow Log Analyzer — scans backend + console output for issues per curl flow.

Usage:
    python3 analyze_flow_logs.py <flow_number> <backend_log> <console_log> <sse_response> [report_out]

Checks:
  1. Tracebacks / unhandled exceptions
  2. Duplicate / wasted LLM calls (same model called >1× per step)
  3. Unexpected coordinator step ordering (per plan_graph_analysis.md)
  4. Unnecessary API calls (e.g. specialist called for Tier 2, tiles fetched when unchanged)
  5. Warnings / errors in backend logs
  6. Flow-specific contract violations
  7. Unnecessary re-renders / state rebuilds
  8. LLM call count (cost awareness)
  9. Activity distribution — detects clustering beyond APD cap
  10. APD consistency — activities_per_day not null in trip_settings
  11. Activity type quality — activity_type is a category, not a title
  12. Tile schema consistency — tiles have geo field alongside coordinates
  13. Deeplink URL quality — catches "#", empty, non-HTTP deeplink_url in tiles
  14. Day card date continuity — no gaps or duplicates in day sequence
  15. Image URL validation — tiles have valid image_url (broken images kill demos)
  16. Arrival/departure bookends — first day has arrival, last day has departure
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ── Expected tool patterns per flow (from plan_graph_analysis.md) ────────────

FLOW_EXPECTED_TOOLS: dict[int, dict[str, Any]] = {
    1: {
        "name": "Greeting — Zero Tools",
        "required_tools": [],
        "forbidden_tools": [
            "extract_trip_fields",
            "get_specialist_advice",
            "search_tiles",
            "build_itinerary",
            "get_local_intel",
            "response",
        ],
        "max_llm_calls": 2,  # classify + conversationalist at most
    },
    2: {
        "name": "Input Gates",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 1,
        "skip_sse": True,  # Flow 2 tests HTTP error codes, not SSE streams
    },
    3: {
        "name": "Tier 1 Specialist — Diving in Bali",
        "required_tools": ["extract_trip_fields", "get_specialist_advice"],
        "forbidden_tools": [],
        "max_llm_calls": 8,
    },
    4: {
        "name": "Tier 2 — Yoga + Cooking",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": ["get_specialist_advice"],
        "max_llm_calls": 6,
    },
    5: {
        "name": "Mixed — Diving + Yoga",
        "required_tools": ["extract_trip_fields", "get_specialist_advice"],
        "forbidden_tools": [],
        "max_llm_calls": 8,
    },
    6: {
        "name": "Origin Detection — 2-Turn",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 12,  # 2 turns
    },
    7: {
        "name": "Settings Change — 2-Turn",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 12,
    },
    8: {
        "name": "Bare Destination",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 6,
    },
    9: {
        "name": "Build Itinerary — GENERATE_PLAN_NOW",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns, specialist + build
    },
    10: {
        "name": "Destination Change — Stale Data Cleared",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 14,
    },
    11: {
        "name": "Cache Survival — L2 Across Session Reset",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 14,
    },
    12: {
        "name": "Google Places Cascade",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 8,
    },
    13: {
        "name": "APD Tile Scaling",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 14,
    },
    14: {
        "name": "Full Plan Golden Path — Rome Cultural",
        "required_tools": ["extract_trip_fields", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
    15: {
        "name": "Deeplink URL Format Validation",
        "required_tools": ["extract_trip_fields", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
    16: {
        "name": "Travelers + Budget Extraction",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 8,
    },
    17: {
        "name": "Suggested Response Round-Trip",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": [],
        "max_llm_calls": 12,  # 2 turns
    },
    18: {
        "name": "Price + Star Rating in Day Cards",
        "required_tools": ["extract_trip_fields", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
    19: {
        "name": "Extend Trip — Preserves Day Cards",
        "required_tools": ["extract_trip_fields", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 18,  # 4 turns (initial + gen + extend + gen)
    },
    20: {
        "name": "Add Tier 1 — Hiking After Plan",
        "required_tools": ["extract_trip_fields", "get_specialist_advice", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 20,  # 4 turns
    },
    21: {
        "name": "Long Trip Tile Density — Extend 10 Days",
        "required_tools": ["extract_trip_fields", "build_itinerary"],
        "forbidden_tools": [],
        "max_llm_calls": 20,  # 4 turns
    },
    22: {
        "name": "Specialist Survival — Origin Add",
        "required_tools": ["extract_trip_fields", "get_specialist_advice"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
    23: {
        "name": "Infeasible Activity — Skiing in Bali",
        "required_tools": ["extract_trip_fields"],
        "forbidden_tools": ["get_specialist_advice"],
        "max_llm_calls": 8,
    },
    24: {
        "name": "Mixed Feasible + Infeasible — Diving + Skiing",
        "required_tools": ["extract_trip_fields", "get_specialist_advice"],
        "forbidden_tools": [],
        "max_llm_calls": 10,
    },
    25: {
        "name": "Activity Switch — Diving → Hiking (Swap)",
        "required_tools": ["extract_trip_fields", "get_specialist_advice"],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
    26: {
        "name": "Trip List + Resume + New Trip Lifecycle",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 0,
        "skip_sse": True,  # Flow 26 is auth-only REST, no SSE streams
    },
    27: {
        "name": "Viator Activity Enrichment",
        "required_tools": [],
        "forbidden_tools": [],
        "max_llm_calls": 14,  # 2 turns
    },
}

# ── Coordinator step ordering contract ───────────────────────────────────────
# From plan_graph_analysis.md: classify → dispatch_specialists || search_tiles → local_intel → build_itinerary → generate_response


class FlowReport:
    """Collects issues found during log analysis."""

    def __init__(self, flow_num: int, flow_name: str):
        self.flow_num = flow_num
        self.flow_name = flow_name
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []
        self.metrics: dict[str, Any] = {}

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)

    def render(self) -> str:
        lines = [
            f"{'=' * 72}",
            f"  FLOW {self.flow_num} REPORT: {self.flow_name}",
            f"{'=' * 72}",
        ]

        # Metrics
        if self.metrics:
            lines.append("")
            lines.append("  METRICS:")
            for k, v in self.metrics.items():
                lines.append(f"    {k}: {v}")

        # Errors
        if self.errors:
            lines.append("")
            lines.append(f"  ERRORS ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"    ✗ {e}")

        # Warnings
        if self.warnings:
            lines.append("")
            lines.append(f"  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")

        # Info
        if self.info:
            lines.append("")
            lines.append(f"  INFO ({len(self.info)}):")
            for i in self.info:
                lines.append(f"    ℹ {i}")

        # Summary line
        lines.append("")
        if self.errors:
            lines.append(
                f"  RESULT: ISSUES FOUND ({len(self.errors)} errors, {len(self.warnings)} warnings)"
            )
        elif self.warnings:
            lines.append(f"  RESULT: WARNINGS ({len(self.warnings)} warnings)")
        else:
            lines.append("  RESULT: CLEAN")
        lines.append(f"{'=' * 72}")
        return "\n".join(lines)


# ── Analysis passes ──────────────────────────────────────────────────────────


def check_tracebacks(backend_log: str, report: FlowReport) -> None:
    """Scan for Python tracebacks in backend output."""
    tb_pattern = re.compile(r"Traceback \(most recent call last\):")
    matches = tb_pattern.findall(backend_log)
    if matches:
        report.error(f"Found {len(matches)} traceback(s) in backend logs")
        # Extract the last line of each traceback (the exception)
        for m in re.finditer(
            r"Traceback \(most recent call last\):.*?(\w+(?:Error|Exception|Warning)[^\n]*)",
            backend_log,
            re.DOTALL,
        ):
            report.error(f"  Exception: {m.group(1)[:200]}")


def check_unhandled_errors(backend_log: str, report: FlowReport) -> None:
    """Scan for ERROR-level log lines."""
    error_lines = re.findall(r"^.*\bERROR\b.*$", backend_log, re.MULTILINE)
    for line in error_lines:
        # Skip noisy/expected errors
        if "Client disconnected" in line:
            continue
        report.error(f"Backend ERROR: {line.strip()[:200]}")


def check_warnings(backend_log: str, report: FlowReport) -> None:
    """Scan for WARNING-level log lines that indicate real issues."""
    warning_lines = re.findall(r"^.*\bWARNING\b.*$", backend_log, re.MULTILINE)
    # Known benign warnings to skip
    benign = [
        "WatchFiles",
        "libuv",
        "Client disconnected",
        "Phase B cache",  # cache misses are normal
    ]
    for line in warning_lines:
        if any(b in line for b in benign):
            continue
        report.warn(f"Backend WARNING: {line.strip()[:200]}")


def check_llm_calls(backend_log: str, flow_num: int, report: FlowReport) -> int:
    """Count and analyze LLM calls for waste/duplication.

    Matches three output formats:
      A. Python logger: ``LEVELNAME:logger_name:message``
      B. _debug_log:    ``[DEBUG] message extras``
      C. log() / Rich:  ``[TAG]           message``
      D. CompactLogger: ``  <emoji> model_name  | p=N c=N ...``

    Patterns target *actual* LLM invocations, not cache hits.
    """
    llm_patterns = [
        # Router extraction + classification (single call per turn)
        (r"\[coordinator\] Classified:", "classifier"),
        # Specialist dispatch: logger or _debug_log
        (
            r"\[coordinator\] Dispatching specialists:"
            r"|\[LLM_SPECIALIST\].*(?:calling LLM|PARALLEL generation|Cache MISS.*calling)",
            "specialist",
        ),
        # Conversationalist: streaming response generation
        (r"\[conversationalist\].*(?:S|s)treaming", "conversationalist"),
        # Experience generator: parallel/single-category generation (not cache hits)
        (
            r"\[EXPERIENCE\].*(?:Parallel generation|fill-day.*generated|Single category)"
            r"|\[EXPERIENCE\].*(?:LLM|generat)(?!.*Cache HIT)",
            "experience_generator",
        ),
        # Local expert LLM call (Phase B) — only the initiation line
        (r"LOCAL_EXPERT Phase B.*calling LLM", "local_expert_llm"),
        # IATA resolver LLM resolution
        (r"\[IATA\].*(?:Resolved|LLM resolution)", "iata_resolver"),
        # Constraint guard feasibility LLM
        (r"\[FEASIBILITY_LLM\]|\[GUARD\].*validate", "constraint_guard_llm"),
        # CompactLogger LLM call indicator (any model)
        (r"\U0001F916\s+\S+\s+\|.*p=\d+.*c=\d+", "llm_call_compact"),
    ]

    call_counts: Counter[str] = Counter()
    for pattern, label in llm_patterns:
        matches = re.findall(pattern, backend_log, re.IGNORECASE)
        if matches:
            call_counts[label] += len(matches)

    total_llm = sum(call_counts.values())
    report.metrics["llm_call_breakdown"] = dict(call_counts)
    report.metrics["total_llm_signals"] = total_llm

    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    max_calls = spec.get("max_llm_calls", 20)
    if total_llm > max_calls:
        report.warn(
            f"High LLM signal count: {total_llm} (expected ≤{max_calls}). "
            f"Breakdown: {dict(call_counts)}"
        )

    # Check for duplicate classifier calls (should be exactly 1 per turn)
    classifier_count = call_counts.get("classifier", 0)
    multi_turn_flows = {6, 7, 9, 10, 11, 13, 14, 15, 17, 18, 19, 20, 21, 22, 25}
    four_turn_flows = {19, 20, 21}
    max_classify = 4 if flow_num in four_turn_flows else (2 if flow_num in multi_turn_flows else 1)
    if classifier_count > max_classify:
        report.warn(f"Excessive classifier calls: {classifier_count} (expected ≤{max_classify})")

    return total_llm


def check_duplicate_api_calls(backend_log: str, report: FlowReport) -> None:
    """Detect duplicate external API calls (same endpoint called multiple times)."""
    # HTTP request patterns in logs
    http_patterns = re.findall(
        r"(?:GET|POST|PUT)\s+(https?://[^\s]+)",
        backend_log,
    )
    url_counts = Counter(http_patterns)
    for url, count in url_counts.items():
        if count > 2:
            report.warn(f"API endpoint called {count}× (possible duplicate): {url[:120]}")


def check_step_ordering(backend_log: str, report: FlowReport) -> None:
    """Verify coordinator steps execute in expected order."""
    # Look for explicit execution plan log (logger.info)
    plan_match = re.search(
        r"\[coordinator\] Execution plan: (.+?) \(steps=(\d+)",
        backend_log,
    )
    if plan_match:
        report.note(f"Execution plan: {plan_match.group(1)} ({plan_match.group(2)} steps)")

    # Detect classification output (logger.info)
    classified = re.search(
        r"\[coordinator\] Classified: intent=(\w+) change_type=(\w+) affects=\[([^\]]*)\]",
        backend_log,
    )
    if classified:
        report.note(
            f"Classified: intent={classified.group(1)} "
            f"change_type={classified.group(2)} affects=[{classified.group(3)}]"
        )

    # Check for "Unknown step type" warnings (indicates step contract violation)
    unknown_steps = re.findall(
        r"\[coordinator\] Unknown step type: (\w+)",
        backend_log,
    )
    for step in unknown_steps:
        report.error(f"Unknown coordinator step type: {step}")

    # Check for partial failures
    partial_fails = re.findall(
        r"\[coordinator\] Partial parallel failure \(([^)]+)\)",
        backend_log,
    )
    for fail in partial_fails:
        report.warn(f"Partial parallel failure: {fail}")


def check_tool_contract(backend_log: str, sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Verify SSE tool calls match expected flow contract."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num)
    if not spec:
        return

    # Extract tools from SSE node_status events
    tools_called: list[str] = []
    for line in sse_data.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "node_status":
            d = obj.get("data", {})
            if d.get("status") == "started":
                tools_called.append(d.get("node", ""))

    report.metrics["tools_called"] = tools_called

    for tool in spec.get("required_tools", []):
        if tool not in tools_called:
            report.warn(f"Expected tool '{tool}' was NOT called")

    for tool in spec.get("forbidden_tools", []):
        if tool in tools_called:
            report.error(f"Forbidden tool '{tool}' was called — violates flow contract")

    # Count turns from complete SSE events
    num_turns = 0
    for line in sse_data.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "complete":
            num_turns += 1
    num_turns = max(num_turns, 1)

    # Check for duplicate tool calls in same turn
    tool_counts = Counter(tools_called)
    for tool, count in tool_counts.items():
        if count > 1 and tool not in ("extract_trip_fields",):
            # response is expected once per turn in multi-turn flows
            if tool == "response":
                max_expected = num_turns
            else:
                multi_turn_flows = {6, 7, 9, 10, 11, 13, 14, 15, 17, 18, 19, 20, 21, 22, 25}
                max_expected = 2 if flow_num in multi_turn_flows else 1
            if count > max_expected:
                report.warn(
                    f"Tool '{tool}' called {count}× (expected ≤{max_expected}) — possible waste"
                )


def check_wasted_operations(backend_log: str, report: FlowReport) -> None:
    """Detect operations that produced no useful output."""
    # Specialist returned None (wasted LLM call)
    null_specialist = re.findall(
        r"\[dispatch_specialist_with_brief\] (\w+) returned None",
        backend_log,
    )
    for topic in null_specialist:
        report.warn(f"Specialist '{topic}' returned None — wasted LLM call")

    # Empty conversationalist response
    if "[coordinator] Empty response from conversationalist" in backend_log:
        report.error("Conversationalist produced empty response — wasted LLM call + bad UX")

    # Itinerary build failed
    build_fails = re.findall(
        r"\[coordinator\] Itinerary build failed: (.+)",
        backend_log,
    )
    for fail in build_fails:
        report.warn(f"Itinerary build failed: {fail[:150]}")

    # Logistics fetch failed
    logistics_fails = re.findall(
        r"\[coordinator\] logistics_node tile fetch failed: (.+)",
        backend_log,
    )
    for fail in logistics_fails:
        report.warn(f"Tile fetch failed: {fail[:150]}")

    # Local intel skeleton failed
    local_fails = re.findall(
        r"\[coordinator\] Local intel skeleton failed: (.+)",
        backend_log,
    )
    for fail in local_fails:
        report.warn(f"Local intel failed: {fail[:150]}")

    # Experience generator failures
    exp_fails = re.findall(
        r"\[EXPERIENCE\].*failed: (.+)",
        backend_log,
    )
    for fail in exp_fails:
        report.warn(f"Experience generator failed: {fail[:150]}")


def check_unnecessary_tile_refreshes(backend_log: str, flow_num: int, report: FlowReport) -> None:
    """Detect unnecessary tile refreshes (e.g., fetching when nothing changed)."""
    # Match logger format: "[coordinator] Refreshing tiles via logistics_node (...)"
    refresh_lines = re.findall(
        r"\[coordinator\] Refreshing tiles via logistics_node \(change_type=(\w+) types=([^)]+)\)",
        backend_log,
    )
    # Also match debug/log format from logistics_node itself
    debug_refreshes = re.findall(
        r"\[LOGISTICS\]\s+Searching (?:flights|hotels|activities)|Searching hotels/activities",
        backend_log,
    )
    total = len(refresh_lines) if refresh_lines else len(debug_refreshes)
    report.metrics["tile_refreshes"] = total

    # Flow 1 (greeting) should have zero tile refreshes
    if flow_num == 1 and total:
        report.error(f"Greeting flow triggered {total} tile refresh(es) — unnecessary")

    # Multiple tile refreshes in single-turn flows is suspicious
    single_turn_flows = {1, 2, 3, 4, 5, 8, 12, 16}
    if flow_num in single_turn_flows and total > 1:
        report.warn(f"Single-turn flow had {total} tile refreshes (expected ≤1)")


def check_cache_behavior(backend_log: str, flow_num: int, report: FlowReport) -> None:
    """Analyze cache hit/miss patterns.

    Matches multiple formats:
      - logger: ``[EXPERIENCE_CACHE] key=... → HIT``
      - _debug_log: ``[TILE_CACHE] Hotels HIT: ...``
      - log(): ``Cache HIT: inputs unchanged ...``
      - CompactLogger: ``✅ Cache HIT ...``
    """
    cache_hits = len(
        re.findall(
            r"(?:cache|CACHE).*(?:HIT|hit)|Cache HIT|CACHE HIT|\u2192 HIT|\u2192\s*HIT",
            backend_log,
            re.IGNORECASE,
        )
    )
    cache_misses = len(
        re.findall(
            r"(?:cache|CACHE).*(?:MISS|miss)|Cache MISS|CACHE MISS|\u2192 MISS|\u2192\s*MISS",
            backend_log,
            re.IGNORECASE,
        )
    )
    report.metrics["cache_hits"] = cache_hits
    report.metrics["cache_misses"] = cache_misses

    # Flow 11 specifically tests cache survival
    if flow_num == 11:
        if cache_hits == 0:
            report.warn("Cache survival flow had 0 cache hits — L2 may not be working")
        else:
            report.note(f"Cache hits: {cache_hits}, misses: {cache_misses}")


def check_turn_timing(backend_log: str, report: FlowReport) -> None:
    """Extract and report turn timing from coordinator logs.

    Matches:
      - logger: ``[coordinator] Turn complete: <reason> (<N> ms)``
      - CompactLogger: ``⏱️  DURATION        | <N>ms (...)``
    """
    # Logger format from coordinator
    timings = re.findall(
        r"\[coordinator\] Turn complete: (.+?) \((\d+) ms\)",
        backend_log,
    )
    for change_type, ms in timings:
        ms_int = int(ms)
        report.metrics[f"turn_time_{change_type}_ms"] = ms_int
        if ms_int > 60000:
            report.warn(f"Turn took {ms_int}ms (>60s) for {change_type} — very slow")
        elif ms_int > 30000:
            report.note(f"Turn took {ms_int}ms (>30s) for {change_type}")

    # CompactLogger request summary timing
    compact_timings = re.findall(
        r"DURATION\s+\|\s*(\d+)ms",
        backend_log,
    )
    for ms_str in compact_timings:
        ms_int = int(ms_str)
        report.metrics.setdefault("turn_time_compact_ms", ms_int)


def check_console_issues(console_log: str, report: FlowReport) -> None:
    """Scan the test console output for assertion failures and infra issues."""
    fail_lines = re.findall(r"^\s*✗\s+(?!INFRA:)(.+)$", console_log, re.MULTILINE)
    for line in fail_lines:
        report.error(f"Assertion failed: {line.strip()}")

    infra_lines = re.findall(r"^\s*✗\s+INFRA:\s+(.+)$", console_log, re.MULTILINE)
    for line in infra_lines:
        report.error(f"Infrastructure failure: {line.strip()}")

    # Check for HTTP error codes in console
    http_errors = re.findall(r"HTTP\s+(\d{3})", console_log)
    for code in http_errors:
        if int(code) >= 500:
            report.error(f"Server error HTTP {code} in test output")


def check_state_rebuilds(backend_log: str, report: FlowReport) -> None:
    """Detect unnecessary state rebuilds or re-serializations."""
    # Categories changed → cleared (expected on destination change, not otherwise)
    clears = re.findall(
        r"\[coordinator\] Categories changed .+ — cleared day_cards \+ activity tiles",
        backend_log,
    )
    report.metrics["category_clears"] = len(clears)
    if len(clears) > 1:
        report.warn(f"Categories cleared {len(clears)}× — possible redundant state rebuild")

    # Per-turn duplicate detection: split log by USER INPUT markers
    turns = re.split(r">>> USER INPUT", backend_log)
    # First segment is pre-turn (server init), skip it
    for i, turn_log in enumerate(turns[1:], start=1):
        # Itinerary builds per turn (should be exactly 0 or 1)
        builds = len(
            re.findall(
                r"\[ItineraryBuilder\].*Starting build",
                turn_log,
            )
        )
        if builds > 1:
            report.warn(f"Turn {i}: ItineraryBuilder ran {builds}× — duplicate build")

        # Tile refreshes per turn (should be exactly 0 or 1)
        refreshes = len(
            re.findall(
                r"\[coordinator\] Refreshing tiles via logistics_node",
                turn_log,
            )
        )
        if refreshes > 1:
            report.warn(f"Turn {i}: Tile refresh triggered {refreshes}× — duplicate refresh")


def check_specialist_dispatch(backend_log: str, flow_num: int, report: FlowReport) -> None:
    """Analyze specialist dispatch patterns for waste.

    Matches:
      - logger: ``[coordinator] Dispatching specialists: ['diving'] (replan=...)``
      - _debug_log: ``[LLM_SPECIALIST] Starting PARALLEL generation for ['diving']``
    """
    # Logger format from coordinator
    dispatches = re.findall(
        r"\[coordinator\] Dispatching specialists: \[([^\]]*)\]",
        backend_log,
    )
    # Also check _debug_log specialist indicators
    debug_dispatches = re.findall(
        r"\[LLM_SPECIALIST\] Starting PARALLEL generation for \[([^\]]*)\]",
        backend_log,
    )
    all_dispatches = dispatches + debug_dispatches
    report.metrics["specialist_dispatches"] = len(all_dispatches)

    for dispatch in all_dispatches:
        topics = [t.strip().strip("'\"") for t in dispatch.split(",") if t.strip()]
        report.note(f"Specialist dispatch: {topics}")

        # Check for duplicate topics in single dispatch
        if len(topics) != len(set(topics)):
            report.warn(f"Duplicate topics in specialist dispatch: {topics}")


def check_sse_event_integrity(sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Verify SSE event stream is well-formed."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        report.note("SSE integrity check skipped (non-SSE flow)")
        return

    event_types: Counter[str] = Counter()
    malformed = 0

    for line in sse_data.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
            etype = obj.get("type", "unknown")
            event_types[etype] += 1
        except (json.JSONDecodeError, ValueError):
            malformed += 1

    report.metrics["sse_events"] = dict(event_types)

    if malformed > 0:
        report.error(f"{malformed} malformed SSE events")

    # Every flow should end with exactly 1 complete event (per turn)
    complete_count = event_types.get("complete", 0)
    if complete_count == 0:
        report.error("No 'complete' SSE event — stream may have been interrupted")

    # Error events indicate problems
    error_count = event_types.get("error", 0)
    if error_count > 0:
        report.error(f"{error_count} SSE error event(s)")


def check_iata_resolver(backend_log: str, report: FlowReport) -> None:
    """Check for unnecessary IATA resolution calls.

    Matches:
      - logger: ``[IATA] Resolved: NYC→JFK, Bali→DPS``
      - generic: ``iata.*resolv``
    """
    iata_calls = re.findall(
        r"\[IATA\].*(?:Resolved|LLM resolution)|iata.*resolv",
        backend_log,
        re.IGNORECASE,
    )
    report.metrics["iata_resolver_calls"] = len(iata_calls)
    # More than 2 per turn is suspicious (origin + destination max)
    if len(iata_calls) > 4:
        report.warn(f"IATA resolver called {len(iata_calls)}× — possible redundant lookups")


def check_persist_failures(backend_log: str, report: FlowReport) -> None:
    """Check for document persistence failures."""
    persist_fails = re.findall(
        r"Failed to persist (?:document|itinerary): (.+)",
        backend_log,
    )
    for fail in persist_fails:
        report.error(f"Persistence failure: {fail[:150]}")


def check_tile_coverage(backend_log: str, report: FlowReport) -> None:
    """Check that tile count is adequate for trip duration.

    Parses: ``Tile scaling: trip=Nd, specialist=Nd, free=Nd, placeable=Nd,``
            ``cats=N, tiles/cat=N, apd=N``
    """
    # Multi-line log: the two halves are on consecutive lines
    scaling_matches = re.findall(
        r"Tile scaling: trip=(\d+)d.*?free=(\d+)d.*?placeable=(\d+)d.*?"
        r"cats=(\d+),\s*tiles/cat=(\d+),\s*apd=(\d+)",
        backend_log,
        re.DOTALL,
    )
    for trip_d, free_d, placeable_d, cats, tiles_per_cat, apd in scaling_matches:
        free = int(free_d)
        tpc = int(tiles_per_cat)
        a = int(apd)
        if free > 0 and tpc > 0:
            coverage = tpc / (free * a) if a else tpc / free
            report.metrics[f"tile_coverage_{free}d"] = f"{tpc}/{free * a} ({coverage:.0%})"
            if coverage < 0.7:
                report.warn(
                    f"Tile coverage {coverage:.0%} — {tpc} tiles for "
                    f"{free} free days × apd={a} ({free * a} slots)"
                )


def check_image_quality(backend_log: str, report: FlowReport) -> None:
    """Detect Unsplash placeholder fallbacks and cache misses."""
    placeholder_hits = re.findall(
        r"\[UNSPLASH-SYNC\] Cache MISS for (unsplash::\S+), using (?:\w+ )?placeholder",
        backend_log,
    )
    no_images = re.findall(
        r"\[UNSPLASH\] No images fetched for (\S+)",
        backend_log,
    )
    report.metrics["unsplash_placeholder_fallbacks"] = len(placeholder_hits)
    if placeholder_hits:
        # Dedupe to show unique keys
        unique_keys = set(placeholder_hits)
        report.warn(
            f"Unsplash placeholder fallback {len(placeholder_hits)}× "
            f"({len(unique_keys)} unique): {', '.join(sorted(unique_keys)[:3])}"
        )
    if no_images:
        for dest in no_images:
            report.warn(f"Unsplash API returned 0 images for '{dest}'")


def check_enrichment_gaps(backend_log: str, report: FlowReport) -> None:
    """Detect partial GP enrichment (Enriched N/M where N < M)."""
    enrichment_lines = re.findall(
        r"\[GOOGLE_PLACES\].*Enriched (\d+)/(\d+) activities for (\S+)",
        backend_log,
    )
    for enriched, total, dest in enrichment_lines:
        if int(enriched) < int(total):
            report.info(
                f"Partial GP enrichment for {dest}: {enriched}/{total} activities (cap-limited)"
            )


# ── SSE semantic checks ──────────────────────────────────────────────────────


def _parse_sse_complete_events(sse_data: str) -> list[dict[str, Any]]:
    """Extract all 'complete' event payloads from SSE stream.

    SSE complete structure:
        {"type": "complete", "data": {"document": {...}, "session_state": {...}}}

    Returns a flat view per event with document fields + session_state merged at
    the top level for convenient access (e.g., evt["day_cards"], evt["tiles"],
    evt["session_state"]).
    """
    events: list[dict[str, Any]] = []
    for line in sse_data.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
            if obj.get("type") == "complete" and isinstance(obj.get("data"), dict):
                raw = obj["data"]
                # Flatten: merge document fields to top level, keep session_state
                flat: dict[str, Any] = {}
                doc = raw.get("document") or {}
                if isinstance(doc, dict):
                    flat.update(doc)
                flat["session_state"] = raw.get("session_state") or {}
                events.append(flat)
        except (json.JSONDecodeError, ValueError):
            pass
    return events


def check_activity_distribution(
    sse_data: str,
    backend_log: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Detect activity clustering — all activities on few days instead of spread.

    Compares max activities on any single day against the APD setting.
    Skips flows without day_cards (greetings, input gates).
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    if not complete_events:
        return

    for evt in complete_events:
        day_cards = evt.get("day_cards") or []
        if not day_cards or not isinstance(day_cards, list):
            continue

        # Extract APD from trip_settings in the SSE payload or session_state
        session_state = evt.get("session_state") or {}
        trip_settings = session_state.get("trip_settings") or evt.get("trip_settings") or {}
        activity_settings = trip_settings.get("activity_settings") or {}
        apd = activity_settings.get("activities_per_day") or 1

        # Count non-buffer activity blocks per day
        day_activity_counts: list[int] = []
        for day in day_cards:
            blocks = day.get("blocks") or []
            activity_count = sum(
                1
                for b in blocks
                if not b.get("is_buffer")
                and b.get("activity_type")
                not in (
                    "arrival",
                    "departure",
                    "check_in",
                    "check_out",
                    "check-in",
                    "check-out",
                    "free_day",
                )
            )
            day_activity_counts.append(activity_count)

        if not day_activity_counts:
            continue

        max_per_day = max(day_activity_counts)
        days_with_activities = sum(1 for c in day_activity_counts if c > 0)
        total_activities = sum(day_activity_counts)

        report.metrics["max_activities_per_day"] = max_per_day
        report.metrics["days_with_activities"] = (
            f"{days_with_activities}/{len(day_activity_counts)}"
        )
        report.metrics["total_activity_blocks"] = total_activities

        # Flag if any day exceeds APD by more than 1 (allow overflow per spec)
        if max_per_day > apd + 1:
            report.error(
                f"Activity clustering: {max_per_day} activities on a single day "
                f"(APD={apd}) — builder placement not respecting per-day cap"
            )
        elif max_per_day > apd:
            report.warn(
                f"Activity overflow: {max_per_day} activities on a day (APD={apd}) "
                f"— acceptable if more tiles than free_days×apd"
            )

        # Flag poor distribution: if >50% of days are empty while others are packed
        if total_activities >= 3 and days_with_activities > 0:
            free_days = sum(
                1
                for day in day_cards
                if not any(
                    b.get("activity_type") in ("arrival", "departure")
                    for b in (day.get("blocks") or [])
                )
            )
            if free_days > 0:
                utilization = days_with_activities / free_days
                if utilization < 0.4:
                    report.warn(
                        f"Poor day utilization: {days_with_activities}/{free_days} free days "
                        f"have activities ({utilization:.0%}) — activities may be clustered"
                    )


def check_apd_consistency(
    sse_data: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Verify activities_per_day is set (not null) in trip_settings.

    The frontend default is "Relaxed 1/day" but must be persisted to the backend.
    A null value causes the builder to default to MAX_BLOCKS_PER_DAY=3.
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    for evt in complete_events:
        session_state = evt.get("session_state") or {}
        trip_settings = session_state.get("trip_settings") or evt.get("trip_settings") or {}
        activity_settings = trip_settings.get("activity_settings") or {}

        # Only check if activity_settings exists (flow actually has activities)
        if not activity_settings:
            continue

        apd = activity_settings.get("activities_per_day")
        if apd is None:
            report.warn(
                "activities_per_day is null in trip_settings — "
                "builder will use MAX_BLOCKS_PER_DAY default instead of UI pace"
            )
        else:
            report.metrics["activities_per_day"] = apd


def check_activity_type_quality(
    sse_data: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Validate activity_type fields contain categories, not titles.

    activity_type should be short category identifiers (e.g., 'diving', 'yoga',
    'cultural'). If it contains long multi-word strings or matches the block's
    title, it's likely a bug where title was used instead of category.
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    bad_types: list[str] = []

    for evt in complete_events:
        day_cards = evt.get("day_cards") or []
        for day in day_cards:
            for block in day.get("blocks") or []:
                activity_type = block.get("activity_type") or ""
                title = block.get("summary") or block.get("title") or ""

                # Skip non-activity blocks
                if activity_type in (
                    "arrival",
                    "departure",
                    "check_in",
                    "check_out",
                    "check-in",
                    "check-out",
                    "free_day",
                    "buffer",
                ):
                    continue

                # Flag: activity_type is suspiciously long (>40 chars = likely a title)
                if len(activity_type) > 40:
                    bad_types.append(f"'{activity_type[:50]}...' (too long)")
                    continue

                # Flag: activity_type exactly matches the title (copy-paste bug)
                if activity_type and title and activity_type == title:
                    bad_types.append(f"'{activity_type[:40]}' == title")

    if bad_types:
        report.error(
            f"activity_type contains title values ({len(bad_types)}×): " + "; ".join(bad_types[:3])
        )


def check_tile_schema_consistency(
    sse_data: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Verify tiles have canonical schema fields (geo, deeplink_url).

    Provider tiles may use coordinates=[lng,lat] and deeplink, but the
    normalized schema should always include geo={lat,lng} and deeplink_url.
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    missing_geo = 0
    total_tiles = 0

    for evt in complete_events:
        tiles = evt.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue

        for tile_id, tile in tiles.items():
            if not isinstance(tile, dict):
                continue
            total_tiles += 1

            # Check geo field exists when coordinates exist
            has_coords = isinstance(tile.get("coordinates"), (list, tuple))
            has_geo = isinstance(tile.get("geo"), dict)
            if has_coords and not has_geo:
                missing_geo += 1

    if total_tiles > 0:
        report.metrics["tiles_checked"] = total_tiles
    if missing_geo > 0:
        report.warn(
            f"{missing_geo}/{total_tiles} tiles have coordinates but no geo field "
            f"— _normalize_tile_fields may not be applied"
        )


def check_deeplink_quality(sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Validate deeplink_url fields are real URLs, not placeholders."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    bad_deeplinks = 0
    total_tiles = 0

    for evt in complete_events:
        tiles = evt.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for tile_id, tile in tiles.items():
            if not isinstance(tile, dict):
                continue
            dl = tile.get("deeplink_url", "")
            if not dl:
                continue
            total_tiles += 1
            if dl == "#" or not dl.startswith("http"):
                bad_deeplinks += 1
                report.error(f"Tile '{tile_id}' has placeholder deeplink: '{dl[:60]}'")

    if total_tiles > 0:
        report.metrics["tiles_with_deeplinks"] = total_tiles
        report.metrics["bad_deeplinks"] = bad_deeplinks


def check_day_card_continuity(sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Verify day_cards dates are sequential with no gaps or duplicates."""
    from datetime import datetime

    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    for evt in complete_events:
        day_cards = evt.get("day_cards") or []
        if len(day_cards) < 2:
            continue

        dates: list[str] = []
        for dc in day_cards:
            d = dc.get("date") or dc.get("day_date") or ""
            if d:
                dates.append(d)

        if len(dates) < 2:
            continue

        # Check for duplicate dates
        if len(dates) != len(set(dates)):
            report.error(f"Duplicate dates in day_cards: {dates}")

        # Check sequential order
        sorted_dates = sorted(dates)
        if dates != sorted_dates:
            report.warn(f"Day cards not in chronological order: {dates}")

        # Check for calendar gaps
        try:
            parsed = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
            for i in range(1, len(parsed)):
                delta = (parsed[i] - parsed[i - 1]).days
                if delta > 1:
                    report.error(
                        f"Gap in day_cards: {dates[i - 1]} -> {dates[i]} "
                        f"({delta - 1} day(s) missing)"
                    )
                elif delta < 1:
                    report.error(f"Non-sequential dates: {dates[i - 1]} -> {dates[i]}")
        except ValueError:
            pass


def check_image_urls(sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Verify image_url fields are valid URLs, not null/empty on visible tiles."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    missing = 0
    total = 0

    for evt in complete_events:
        tiles = evt.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for tile_id, tile in tiles.items():
            if not isinstance(tile, dict):
                continue
            # Flight tiles legitimately have no image_url
            if tile.get("type") not in ("hotel", "activity"):
                continue
            total += 1
            img = tile.get("image_url", "")
            if not img or not img.startswith("http"):
                missing += 1

    if missing > 0:
        report.warn(f"{missing}/{total} tiles missing valid image_url")
    if total > 0:
        report.metrics["tiles_with_images"] = f"{total - missing}/{total}"


def check_specialist_tile_presence(
    sse_data: str,
    backend_log: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """When specialist advice was dispatched, verify matching tiles exist.

    If get_specialist_advice was called successfully but zero tiles with
    matching specialist tags appear in the output, the specialist result
    was silently dropped (e.g. TripBrief crash).
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    # Check if specialist was dispatched
    specialist_topics: list[str] = []
    for m in re.finditer(r"\[dispatch_specialist_with_brief\] Dispatching (\w+)", backend_log):
        specialist_topics.append(m.group(1).lower())

    if not specialist_topics:
        return

    complete_events = _parse_sse_complete_events(sse_data)
    for evt in complete_events:
        tiles = evt.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue

        for topic in specialist_topics:
            matching = 0
            for tile_id, tile in tiles.items():
                if not isinstance(tile, dict):
                    continue
                tags = [t.lower() for t in (tile.get("tags") or [])]
                title = (tile.get("title") or "").lower()
                meta = tile.get("meta") or {}
                source_cats = [c.lower() for c in (meta.get("source_categories") or [])]
                if (
                    topic in tags
                    or topic in title
                    or topic in source_cats
                    or tile_id.startswith(f"exp_{topic}")
                ):
                    matching += 1

            report.metrics[f"specialist_{topic}_tiles"] = matching
            if matching == 0:
                report.error(
                    f"Specialist '{topic}' was dispatched but zero matching tiles "
                    f"in output — specialist result may have been silently dropped"
                )


def check_day_fill_rate(
    sse_data: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Check that interior days have adequate activity fill rate.

    Warn if < 50%, error if < 30%. Skips arrival/departure day.
    """
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    for evt in complete_events:
        day_cards = evt.get("day_cards") or []
        if len(day_cards) < 3:
            continue

        # Interior days = skip first and last (arrival/departure)
        interior = day_cards[1:-1]
        with_acts = 0
        for day in interior:
            blocks = day.get("blocks") or []
            has_activity = any(b.get("booking_category") == "activity" for b in blocks)
            if has_activity:
                with_acts += 1

        total = max(1, len(interior))
        rate = with_acts / total
        report.metrics["day_fill_rate"] = f"{with_acts}/{total} ({rate:.0%})"

        if rate < 0.3:
            report.error(
                f"Day fill rate {rate:.0%} — {with_acts}/{total} interior days "
                f"have activities (< 30% threshold)"
            )
        elif rate < 0.5:
            report.warn(
                f"Day fill rate {rate:.0%} — {with_acts}/{total} interior days "
                f"have activities (< 50% threshold)"
            )


def check_bookend_blocks(sse_data: str, flow_num: int, report: FlowReport) -> None:
    """Verify first day has arrival block, last day has departure block."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    if spec.get("skip_sse"):
        return

    complete_events = _parse_sse_complete_events(sse_data)
    for evt in complete_events:
        day_cards = evt.get("day_cards") or []
        if len(day_cards) < 2:
            continue

        # First day should have arrival
        first_blocks = day_cards[0].get("blocks") or []
        has_arrival = any(b.get("activity_type") in ("arrival",) for b in first_blocks)
        if not has_arrival:
            report.error("First day_card missing arrival block")

        # Last day should have departure
        last_blocks = day_cards[-1].get("blocks") or []
        has_departure = any(b.get("activity_type") in ("departure",) for b in last_blocks)
        if not has_departure:
            report.error("Last day_card missing departure block")


# ── Main ─────────────────────────────────────────────────────────────────────


def _audit_inputs(
    backend_log: str,
    console_log: str,
    sse_data: str,
    flow_num: int,
    report: FlowReport,
) -> None:
    """Sanity-check that all three data sources were captured."""
    skip_sse = FLOW_EXPECTED_TOOLS.get(flow_num, {}).get("skip_sse", False)

    bl = len(backend_log.splitlines())
    cl = len(console_log.splitlines())
    sl = len(sse_data.splitlines())
    report.metrics["input_lines"] = f"backend={bl} console={cl} sse={sl}"

    if bl == 0 and flow_num not in (2,):
        report.warn("Backend trace is EMPTY — log capture may be broken")
    if cl == 0 and flow_num not in (2,):
        report.warn("Console log is EMPTY — extraction may be broken")
    if sl == 0 and not skip_sse:
        report.warn("SSE response is EMPTY — curl capture may be broken")


def analyze_flow(
    flow_num: int,
    backend_log: str,
    console_log: str,
    sse_data: str,
) -> FlowReport:
    """Run all analysis passes on a flow's logs."""
    spec = FLOW_EXPECTED_TOOLS.get(flow_num, {})
    flow_name = spec.get("name", f"Flow {flow_num}")

    report = FlowReport(flow_num, flow_name)

    # Audit inputs first — warns if any data source is empty
    _audit_inputs(backend_log, console_log, sse_data, flow_num, report)

    # Run all checks
    check_tracebacks(backend_log, report)
    check_unhandled_errors(backend_log, report)
    check_warnings(backend_log, report)
    check_llm_calls(backend_log, flow_num, report)
    check_duplicate_api_calls(backend_log, report)
    check_step_ordering(backend_log, report)
    check_tool_contract(backend_log, sse_data, flow_num, report)
    check_wasted_operations(backend_log, report)
    check_unnecessary_tile_refreshes(backend_log, flow_num, report)
    check_cache_behavior(backend_log, flow_num, report)
    check_turn_timing(backend_log, report)
    check_console_issues(console_log, report)
    check_state_rebuilds(backend_log, report)
    check_specialist_dispatch(backend_log, flow_num, report)
    check_sse_event_integrity(sse_data, flow_num, report)
    check_iata_resolver(backend_log, report)
    check_persist_failures(backend_log, report)
    check_tile_coverage(backend_log, report)
    check_image_quality(backend_log, report)
    check_enrichment_gaps(backend_log, report)
    check_activity_distribution(sse_data, backend_log, flow_num, report)
    check_apd_consistency(sse_data, flow_num, report)
    check_activity_type_quality(sse_data, flow_num, report)
    check_tile_schema_consistency(sse_data, flow_num, report)
    check_deeplink_quality(sse_data, flow_num, report)
    check_day_card_continuity(sse_data, flow_num, report)
    check_image_urls(sse_data, flow_num, report)
    check_bookend_blocks(sse_data, flow_num, report)
    check_specialist_tile_presence(sse_data, backend_log, flow_num, report)
    check_day_fill_rate(sse_data, flow_num, report)

    return report


def main() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python3 analyze_flow_logs.py <flow_num> <backend_log> <console_log> <sse_response> [report_out]",
            file=sys.stderr,
        )
        sys.exit(1)

    flow_num = int(sys.argv[1])
    backend_log_path = Path(sys.argv[2])
    console_log_path = Path(sys.argv[3])
    sse_path = Path(sys.argv[4])
    report_out = Path(sys.argv[5]) if len(sys.argv) > 5 else None

    backend_log = backend_log_path.read_text() if backend_log_path.exists() else ""
    console_log = console_log_path.read_text() if console_log_path.exists() else ""
    sse_data = sse_path.read_text() if sse_path.exists() else ""

    report = analyze_flow(flow_num, backend_log, console_log, sse_data)
    output = report.render()

    print(output)

    if report_out:
        report_out.write_text(output + "\n")

    # Exit 1 if errors found
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
