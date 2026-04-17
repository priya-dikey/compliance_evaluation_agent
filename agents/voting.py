"""
agents/voting.py
Multi-evaluator voting aggregation with compliance veto,
spread threshold, and confidence weighting.
"""


EVALUATOR_WEIGHTS = {
    "compliance":    0.5,   # legal risk — highest
    "accessibility": 0.3,   # regulatory risk
    "ux":            0.2,   # best practice
    # geo is advisory — informs but doesn't directly affect weighted score
}

DISAGREEMENT_PROTOCOL = {
    "compliance_veto_threshold": 2,    # score <= 2 triggers veto
    "spread_threshold":          2,    # score spread > 2 → human review
    "min_confidence":            0.75, # below this → human review
}


class VotingAggregator:
    def aggregate(self, ai_results: dict) -> dict:
        scores = {}
        confidences = {}
        all_violations = []

        for key in ["compliance", "accessibility", "ux"]:
            result = ai_results.get(key, {})
            score = result.get("score", 0)
            confidence = result.get("confidence", 0.0)
            scores[key] = score
            confidences[key] = confidence
            for v in result.get("violations", []):
                v["source_evaluator"] = key
                all_violations.append(v)

        # Weighted score (confidence-adjusted)
        weighted_score = 0.0
        total_weight = 0.0
        for key, weight in EVALUATOR_WEIGHTS.items():
            if key in scores:
                conf = confidences.get(key, 1.0)
                adjusted_weight = weight * conf
                weighted_score += scores[key] * adjusted_weight
                total_weight += adjusted_weight

        weighted_score = (weighted_score / total_weight
                          if total_weight > 0 else 0.0)
        weighted_score_normalized = weighted_score / 5.0  # 0-1

        # Compliance veto
        compliance_vetoed = (
            scores.get("compliance", 5) <=
            DISAGREEMENT_PROTOCOL["compliance_veto_threshold"]
        )

        # Disagreement detection
        active_scores = [v for v in scores.values() if v > 0]
        spread = (max(active_scores) - min(active_scores)
                  if len(active_scores) >= 2 else 0)
        high_spread = spread > DISAGREEMENT_PROTOCOL["spread_threshold"]

        disagreement_details = []
        if high_spread:
            disagreement_details.append({
                "type": "score_spread",
                "spread": spread,
                "scores": scores,
                "note": "evaluators disagree significantly — human review needed"
            })

        # Confidence
        mean_confidence = (sum(confidences.values()) / len(confidences)
                           if confidences else 0.0)
        low_confidence = (mean_confidence <
                          DISAGREEMENT_PROTOCOL["min_confidence"])
        if low_confidence:
            disagreement_details.append({
                "type": "low_confidence",
                "mean_confidence": mean_confidence,
                "note": "insufficient confidence for automated decision"
            })

        human_review_required = (
            compliance_vetoed or high_spread or low_confidence or
            any(v.get("severity") == "critical" and
                v.get("confidence", 1.0) < 0.85
                for v in all_violations)
        )

        return {
            "scores_per_evaluator":   scores,
            "confidences_per_evaluator": confidences,
            "weighted_score":         round(weighted_score_normalized, 3),
            "mean_confidence":        round(mean_confidence, 3),
            "confidence":             round(mean_confidence, 3),
            "compliance_vetoed":      compliance_vetoed,
            "score_spread":           spread,
            "human_review_required":  human_review_required,
            "disagreement_details":   disagreement_details,
            "all_violations":         all_violations,
            "critical_count":         sum(
                1 for v in all_violations
                if v.get("severity") == "critical"
            ),
            "high_count":             sum(
                1 for v in all_violations
                if v.get("severity") == "high"
            ),
        }
