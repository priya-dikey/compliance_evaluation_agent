"""
tests/evals/test_compliance_eval.py
Eval tests for AIEvaluators.evaluate_compliance() and evaluate_accessibility().

Run:
    pytest tests/evals/ -v
    pytest tests/evals/test_compliance_eval.py -v -k "schema"  # schema only (no API cost)
"""

import pytest
from agents.ai_evaluators import AIEvaluators
from tests.evals.fixtures import (
    FAILING_BANNER, PASSING_BANNER,
    AXE_VIOLATIONS_KEYBOARD, AXE_VIOLATIONS_CLEAN,
    GDPR_RULES,
)

pytestmark = pytest.mark.asyncio


# ── Output schema tests (cheap — verify structure before accuracy) ────────────

async def test_compliance_output_schema():
    """Agent always returns parseable dict with required keys."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(FAILING_BANNER)

    required = {"score", "violations", "compliant", "confidence", "reasoning", "tokens_used"}
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"
    assert 1 <= result["score"] <= 5, "Score must be 1–5"
    assert 0.0 <= result["confidence"] <= 1.0, "Confidence must be 0–1"
    assert isinstance(result["violations"], list)
    assert isinstance(result["compliant"], bool)


async def test_compliance_violation_schema():
    """Each violation has the required fields with valid values."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(FAILING_BANNER)

    valid_severities = {"critical", "high", "medium", "low"}
    for v in result["violations"]:
        assert {"rule", "severity", "finding", "evidence", "confidence"}.issubset(v.keys()), \
            f"Violation missing keys: {v}"
        assert v["severity"] in valid_severities, f"Bad severity: {v['severity']}"
        assert 0.0 <= v["confidence"] <= 1.0, f"Bad confidence: {v['confidence']}"
        assert len(v["finding"]) > 0, "Finding must not be empty"


async def test_accessibility_output_schema():
    """Accessibility evaluator returns correct schema."""
    ctx = {**PASSING_BANNER, "axe_violations": AXE_VIOLATIONS_CLEAN, "device": "Desktop Chrome"}
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_accessibility(ctx)

    required = {"score", "violations", "keyboard_navigable", "screen_reader_compatible",
                "focus_trap_correct", "aria_role_correct", "confidence", "reasoning"}
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"
    assert isinstance(result["keyboard_navigable"], bool)
    assert isinstance(result["screen_reader_compatible"], bool)


async def test_ux_output_schema():
    """UX evaluator returns correct schema."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_ux(FAILING_BANNER)

    required = {"score", "violations", "accept_reject_prominence_equal",
                "dismissible_without_choice", "reject_requires_extra_clicks",
                "confidence", "reasoning"}
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"


# ── Accuracy tests (cost: ~3 Sonnet calls each) ───────────────────────────────

async def test_compliance_detects_pre_consent_cookies():
    """Must flag pre-consent cookie tracking as a violation."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(FAILING_BANNER)

    assert result["compliant"] is False
    assert result["score"] <= 2, f"Expected score ≤ 2, got {result['score']}"

    findings_text = " ".join(
        v.get("finding", "") + v.get("rule", "") for v in result["violations"]
    ).lower()
    assert any(kw in findings_text for kw in ("cookie", "consent", "tracking", "prior")), \
        "Must mention pre-consent cookie violation in findings"


async def test_compliance_detects_missing_reject_button():
    """Must flag absence of reject button as a violation."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(FAILING_BANNER)

    findings_text = " ".join(
        v.get("finding", "") + v.get("rule", "") for v in result["violations"]
    ).lower()
    assert any(kw in findings_text for kw in ("reject", "decline", "equal", "choice")), \
        "Must mention missing reject/equal-choice in findings"


async def test_compliance_passes_clean_banner():
    """Clean banner should score high and be marked compliant."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(PASSING_BANNER)

    assert result["score"] >= 4, f"Expected score ≥ 4, got {result['score']}"
    assert result["confidence"] >= 0.6, f"Expected confidence ≥ 0.6, got {result['confidence']}"
    critical = [v for v in result["violations"] if v.get("severity") == "critical"]
    assert not critical, f"No critical violations expected on passing banner: {critical}"


async def test_compliance_confidence_on_clear_violation():
    """Confidence must be high when violations are unambiguous."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(FAILING_BANNER)

    assert result["confidence"] >= 0.7, \
        f"Expected high confidence on clear violations, got {result['confidence']}"


async def test_accessibility_detects_keyboard_violations():
    """Must surface keyboard/focus axe violations in its output."""
    ctx = {
        **FAILING_BANNER,
        "axe_violations": AXE_VIOLATIONS_KEYBOARD,
        "device": "Desktop Chrome",
    }
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_accessibility(ctx)

    assert result["score"] <= 3, f"Expected score ≤ 3 with critical axe violations, got {result['score']}"
    findings_text = " ".join(
        v.get("finding", "") + v.get("evidence", "") for v in result["violations"]
    ).lower()
    assert any(kw in findings_text for kw in ("focus", "keyboard", "trap", "focusable")), \
        "Must reference keyboard/focus violations from axe results"


async def test_ux_detects_dark_pattern_contrast():
    """Must flag unequal accept/reject prominence from contrast data."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_ux(FAILING_BANNER)

    assert result["accept_reject_prominence_equal"] is False, \
        "3.4 point contrast difference must be flagged as unequal prominence"


# ── Regression guard ──────────────────────────────────────────────────────────

async def test_no_hallucinated_violations_on_clean_banner():
    """Agent must not invent violations when all measurements are clean."""
    ai = AIEvaluators(GDPR_RULES)
    result = await ai.evaluate_compliance(PASSING_BANNER)

    critical = [v for v in result["violations"] if v.get("severity") == "critical"]
    assert len(critical) == 0, \
        f"False positive critical violations on clean banner: {critical}"
