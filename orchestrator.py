"""
Hybrid QA Agent — Orchestrator
Entry point: python orchestrator.py --url https://en.giesswein.com/
"""

import asyncio
import json
import os
import sys
import uuid
import time
import argparse
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone

from config.compliance_rules import fetch_compliance_rules
from reports.generate_report import generate_from_dict
from agents.deterministic import DeterministicAgent
from agents.self_healing import SelfHealingAgent
from agents.ai_evaluators import AIEvaluators
from agents.voting import VotingAggregator
from agents.scenario_mapper import ScenarioMapper
from evaluation import final_evaluation

TARGET_URL = "https://en.giesswein.com/"

TEST_CONTEXTS = [
    {"name": "fresh_visitor",      "cookies": {}},
    {"name": "returning_accepted", "cookies": {"CookieConsent": "true"}},
    {"name": "returning_rejected", "cookies": {"CookieConsent": "false"}},
    {"name": "expired_consent",    "cookies": {
        "CookieConsent": "true", "consent_date": "2022-01-01"}},
]

GEO_CONTEXTS = [
    {"name": "EU_Germany", "locale": "de-DE",
     "timezone": "Europe/Berlin", "opt_in_required": True, "law": "GDPR"},
]

DEVICES = [
    {"name": "Desktop Chrome",  "browser": "chromium", "viewport": None,
     "is_mobile": False},
    {"name": "Desktop Firefox", "browser": "firefox",  "viewport": None,
     "is_mobile": False},
    {"name": "Desktop Safari",  "browser": "webkit",   "viewport": None,
     "is_mobile": False},
    {"name": "iPhone 14",       "browser": "webkit",
     "viewport": {"width": 390, "height": 844}, "is_mobile": True},
    {"name": "Pixel 7",         "browser": "chromium",
     "viewport": {"width": 412, "height": 915}, "is_mobile": True},
]


@dataclass
class ReportState:
    url: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    start_time: float = field(default_factory=time.time)

    compliance_rules: dict = field(default_factory=dict)
    compliance_rules_source: list = field(default_factory=list)
    test_contexts_run: list = field(default_factory=list)

    deterministic: dict = field(default_factory=dict)
    ai_evaluations: dict = field(default_factory=dict)
    voting: dict = field(default_factory=dict)
    self_healing_events: list = field(default_factory=list)

    final: dict = field(default_factory=dict)
    scenario_results: list = field(default_factory=list)
    tokens_used: int = 0
    errors: list = field(default_factory=list)


async def run(url: str, fast: bool = False) -> ReportState:
    state = ReportState(url=url)
    print(f"\n[orchestrator] run_id={state.run_id}")
    print(f"[orchestrator] target={url}")

    # ── Step 0: Compliance rules ──────────────────────────────────────────
    print("\n[0] Fetching compliance rules...")
    rules_result = await fetch_compliance_rules()
    if rules_result["error"]:
        print(f"[ERROR] {rules_result['error']}")
        state.errors.append(rules_result["error"])
        sys.exit(1)
    state.compliance_rules = rules_result["rules"]
    state.compliance_rules_source = rules_result["sources"]
    print(f"[0] Rules loaded from: {rules_result['sources']}")

    # ── Step 1: Deterministic layer ───────────────────────────────────────
    print("\n[1] Running deterministic layer...")
    det_agent = DeterministicAgent(url)
    self_healer = SelfHealingAgent()
    # Share CMP profile so self-healer uses site-specific selectors
    self_healer.set_cmp_profile(det_agent.cmp_profile)

    devices_to_run = [DEVICES[0]] if fast else DEVICES
    contexts_to_run = [TEST_CONTEXTS[0]] if fast else TEST_CONTEXTS

    det_results = await det_agent.run(
        devices=devices_to_run,
        contexts=contexts_to_run,
        geo_contexts=GEO_CONTEXTS[:1] if fast else GEO_CONTEXTS,
        self_healer=self_healer,
    )
    state.deterministic = det_results
    state.self_healing_events = self_healer.get_log()
    print(f"[1] Deterministic score: {det_results.get('score', 0):.2f}")

    # ── Step 2: AI evaluation layer ───────────────────────────────────────
    print("\n[2] Running AI evaluation layer...")
    ai = AIEvaluators(state.compliance_rules)

    # Use primary device + fresh visitor context for AI evaluation
    primary_context = det_results.get("primary_context", {})
    # Inject CMP metadata so evaluators can reference it in prompts
    primary_context["cmp_name"]      = det_agent.cmp_profile.name
    primary_context["banner_format"] = det_results.get("banner_format", "unknown")

    eval_names = ["compliance", "accessibility", "ux"]
    eval_coros = [
        ai.evaluate_compliance(primary_context),
        ai.evaluate_accessibility(primary_context),
        ai.evaluate_ux(primary_context),
    ]
    eval_outputs = await asyncio.gather(*eval_coros, return_exceptions=True)

    ai_results = {}
    for name, result in zip(eval_names, eval_outputs):
        if isinstance(result, Exception):
            print(f"[2] {name} evaluator failed: {result}")
            state.errors.append(f"AI evaluator {name}: {result}")
            ai_results[name] = {"score": 0, "violations": [],
                                "confidence": 0, "error": str(result)}
        else:
            ai_results[name] = result
            state.tokens_used += result.get("tokens_used", 0)
            print(f"[2] {name}: score={result.get('score',0)}/5 "
                  f"confidence={result.get('confidence',0):.2f}")

    state.ai_evaluations = ai_results

    # ── Step 3: Voting aggregation ────────────────────────────────────────
    print("\n[3] Aggregating evaluator votes...")
    voter = VotingAggregator()
    vote_result = voter.aggregate(ai_results)
    state.voting = vote_result
    print(f"[3] Weighted score: {vote_result['weighted_score']:.2f} "
          f"confidence: {vote_result['confidence']:.2f}")
    if vote_result["compliance_vetoed"]:
        print("[3] ⚠ Compliance veto triggered")
    if vote_result["human_review_required"]:
        print("[3] ⚠ Human review required")

    # ── Step 4: Final evaluation ──────────────────────────────────────────
    print("\n[4] Computing final evaluation...")
    state.final = final_evaluation(
        deterministic=state.deterministic,
        ai_results=state.ai_evaluations,
        voting=state.voting,
        self_healing_meta={"used": bool(state.self_healing_events),
                           "events": state.self_healing_events},
        compliance_rules=state.compliance_rules,
    )

    duration_ms = int((time.time() - state.start_time) * 1000)
    state.final["duration_ms"] = duration_ms

    # ── Step 5: Map results to feature file scenarios ─────────────────────────
    print("\n[5] Mapping results to feature scenarios...")
    state.scenario_results = ScenarioMapper().map(build_output(state))
    counts = {"PASS": 0, "FAIL": 0, "PARTIAL": 0, "SKIP": 0}
    for s in state.scenario_results:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    print(f"[5] Scenarios: {counts['PASS']} pass · {counts['FAIL']} fail · "
          f"{counts['PARTIAL']} partial · {counts['SKIP']} skip")

    print(f"\n{'='*60}")
    print(f"  STATUS:          {state.final['status']}")
    print(f"  SCORE:           {state.final['score']:.2f}")
    print(f"  CONFIDENCE:      {state.final['confidence']:.2f}")
    print(f"  RISK:            {state.final['risk']}")
    print(f"  PIPELINE ACTION: {state.final['pipeline_action']}")
    print(f"  DURATION:        {duration_ms}ms")
    print(f"  TOKENS USED:     {state.tokens_used}")
    print(f"{'='*60}\n")

    return state


def build_output(state: ReportState) -> dict:
    return {
        "meta": {
            "run_id":                  state.run_id,
            "timestamp":               state.timestamp,
            "target_url":              state.url,
            "duration_ms":             state.final.get("duration_ms", 0),
            "tokens_used":             state.tokens_used,
            "compliance_rules_source": state.compliance_rules_source,
            "self_healing_events":     state.self_healing_events,
            "errors":                  state.errors,
        },
        "compliance_rules":   state.compliance_rules,
        "test_contexts_run":  state.test_contexts_run,
        "deterministic":      state.deterministic,
        "ai_evaluations":     state.ai_evaluations,
        "voting":             state.voting,
        "self_healing": {
            "used":     bool(state.self_healing_events),
            "events":   state.self_healing_events,
            "strategy": (state.self_healing_events[-1].get("level", "PRIMARY")
                         if state.self_healing_events else "PRIMARY"),
        },
        "final":            state.final,
        "scenario_results": state.scenario_results,
    }


async def main():
    parser = argparse.ArgumentParser(description="Hybrid QA Agent")
    parser.add_argument("--url", default=TARGET_URL)
    parser.add_argument("--output", default="reports/report.json")
    parser.add_argument("--fast", action="store_true",
                        help="Run only primary device + fresh context")
    args = parser.parse_args()

    state = await run(args.url, fast=args.fast)
    output = build_output(state)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[orchestrator] JSON report  → {args.output}")

    html_path = args.output.replace(".json", ".html")
    generate_from_dict(output, html_path)
    print(f"[orchestrator] HTML report  → {html_path}")

    # Exit code for CI/CD
    action = state.final.get("pipeline_action", "WARN")
    sys.exit(1 if action == "BLOCK" else 0)


if __name__ == "__main__":
    asyncio.run(main())
