"""
evaluation.py
Final scoring, pipeline action decision, and report assembly.
Deterministic checks weighted 0.6, AI reasoning weighted 0.4.
Pipeline BLOCK requires: critical + confidence >= 0.85 + deterministic evidence.
"""


def compute_deterministic_score(results: dict) -> dict:
    """
    Weight critical compliance checks.
    Returns score 0.0-1.0 and penalty breakdown.
    """
    score = 1.0
    penalties = []
    critical_failures = []

    # pre_consent_cookies — weight 0.40 (highest legal risk)
    if results.get("pre_consent_cookies"):
        cookie_names = list(results["pre_consent_cookies"].keys())
        penalties.append({
            "check":   "pre_consent_cookies",
            "weight":  0.40,
            "detail":  f"Tracking cookies before consent: {cookie_names}",
            "critical": True,
        })
        critical_failures.append("pre_consent_cookies")
        score -= 0.40

    # reject_button_missing — weight 0.30
    if not results.get("reject_button_found", False):
        penalties.append({
            "check":    "reject_button_missing",
            "weight":   0.30,
            "detail":   "No reject/decline button found in banner",
            "critical": True,
        })
        critical_failures.append("reject_button_missing")
        score -= 0.30

    # consent_mode_v2_incorrect — weight 0.20
    cmv2 = results.get("consent_mode_v2", {})
    if cmv2.get("detected") and not cmv2.get("ad_storage_default_denied"):
        penalties.append({
            "check":    "consent_mode_v2_incorrect",
            "weight":   0.20,
            "detail":   "Consent Mode v2 detected but ad_storage not denied by default",
            "critical": False,
        })
        score -= 0.20

    # axe critical violations — weight 0.10
    critical_axe = [
        v for v in results.get("axe_violations", [])
        if v.get("impact") == "critical"
    ]
    if critical_axe:
        penalty = min(0.10, 0.03 * len(critical_axe))
        penalties.append({
            "check":    "axe_critical",
            "weight":   penalty,
            "detail":   f"{len(critical_axe)} critical axe violations",
            "critical": False,
        })
        score -= penalty

    # contrast ratio dark pattern — advisory (no score penalty — AI handles)
    contrast = results.get("contrast_ratios", {})
    ratio_diff = contrast.get("ratio_diff", 0)
    if ratio_diff and ratio_diff > 3.0:
        penalties.append({
            "check":    "contrast_dark_pattern",
            "weight":   0,
            "detail":   f"Accept/reject contrast ratio difference: {ratio_diff} (possible dark pattern)",
            "critical": False,
            "advisory": True,
        })

    return {
        "score":            max(0.0, round(score, 3)),
        "penalties":        penalties,
        "critical_failures": critical_failures,
    }


def aggregate_ai_scores(ai_results: dict) -> dict:
    """
    Pull voting result through to final format.
    """
    voting = ai_results.get("voting", {})
    return {
        "weighted_score":        voting.get("weighted_score", 0.0),
        "confidence":            voting.get("confidence", 0.0),
        "compliance_vetoed":     voting.get("compliance_vetoed", False),
        "human_review_required": voting.get("human_review_required", False),
        "critical_count":        voting.get("critical_count", 0),
        "high_count":            voting.get("high_count", 0),
        "all_violations":        voting.get("all_violations", []),
    }


def calculate_confidence(ai_results: dict) -> float:
    """
    Mean confidence across evaluators, penalised by spread.
    """
    voting = ai_results.get("voting", {})
    base_confidence = voting.get("mean_confidence", 0.0)
    spread = voting.get("score_spread", 0)
    # Penalise confidence when evaluators disagree
    spread_penalty = min(0.3, spread * 0.05)
    return max(0.0, round(base_confidence - spread_penalty, 3))


def final_evaluation(
    deterministic: dict,
    ai_results: dict,
    voting: dict,
    self_healing_meta: dict,
    compliance_rules: dict,
) -> dict:
    """
    Combine deterministic (0.6) + AI (0.4).
    Deterministic weighted higher for compliance-critical rules.
    Determine pipeline_action.
    """
    det_score_result = compute_deterministic_score(deterministic)
    det_score = det_score_result["score"]
    det_critical = det_score_result["critical_failures"]

    ai_score_result = aggregate_ai_scores({"voting": voting})
    ai_score = ai_score_result["weighted_score"]
    confidence = calculate_confidence({"voting": voting})

    # Combined score: deterministic weighted higher
    combined_score = round(det_score * 0.6 + ai_score * 0.4, 3)

    # Status
    compliance_vetoed = voting.get("compliance_vetoed", False)
    human_review = voting.get("human_review_required", False)

    if det_critical or compliance_vetoed:
        status = "FAIL"
    elif combined_score >= 0.7 and not human_review:
        status = "PASS"
    elif self_healing_meta.get("used") and any(
        e.get("compliance_impact") for e in
        self_healing_meta.get("events", [])
    ):
        status = "PARTIAL"
    else:
        status = "WARN"

    # Risk
    if det_critical or (ai_score_result["critical_count"] > 0
                        and confidence >= 0.85):
        risk = "CRITICAL"
    elif combined_score < 0.5 or compliance_vetoed:
        risk = "HIGH"
    elif combined_score < 0.75 or human_review:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    # Pipeline action — BLOCK requires all three conditions
    critical_violations = [
        v for v in ai_score_result["all_violations"]
        if v.get("severity") == "critical"
        and v.get("confidence", 0) >= 0.85
    ]
    has_deterministic_evidence = bool(det_critical)
    block_conditions_met = (
        bool(critical_violations)
        and confidence >= 0.85
        and has_deterministic_evidence
    )

    if block_conditions_met or status == "FAIL":
        pipeline_action = "BLOCK"
    elif risk in ("HIGH", "MEDIUM") or human_review:
        pipeline_action = "WARN"
    else:
        pipeline_action = "PASS"

    # Reasoning trace
    reasoning_trace = []
    if det_critical:
        reasoning_trace.append(
            f"Deterministic failures: {', '.join(det_critical)}")
    if compliance_vetoed:
        reasoning_trace.append("Compliance evaluator veto triggered")
    if human_review:
        reasoning_trace.append("Human review required — low confidence or disagreement")
    for v in critical_violations:
        reasoning_trace.append(
            f"Critical: [{v.get('source_evaluator')}] {v.get('finding')}")

    return {
        "score":                  combined_score,
        "deterministic_score":    det_score,
        "ai_score":               ai_score,
        "confidence":             confidence,
        "status":                 status,
        "risk":                   risk,
        "pipeline_action":        pipeline_action,
        "human_review_required":  human_review,
        "compliance_vetoed":      compliance_vetoed,
        "deterministic_penalties": det_score_result["penalties"],
        "critical_violations":    critical_violations,
        "reasoning_trace":        reasoning_trace,
    }
