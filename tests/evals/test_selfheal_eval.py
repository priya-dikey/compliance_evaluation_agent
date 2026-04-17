"""
tests/evals/test_selfheal_eval.py
Eval tests for SelfHealingAgent._classify_failure().

The most safety-critical eval: verifies the agent never heals a
FUNCTIONAL_REMOVAL as SELECTOR_DRIFT (which would mask a real regression).

Run:
    pytest tests/evals/test_selfheal_eval.py -v
"""

import pytest
from agents.self_healing import SelfHealingAgent
from tests.evals.fixtures import (
    HTML_SELECTOR_DRIFT,
    HTML_FUNCTIONAL_REMOVAL,
    HTML_FUNCTIONAL_CHANGE,
)

pytestmark = pytest.mark.asyncio


# ── Output schema ─────────────────────────────────────────────────────────────

async def test_classify_output_schema():
    """_classify_failure always returns a valid dict regardless of HTML."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "accept_button", "Accept all cookies button", HTML_SELECTOR_DRIFT)

    required = {"change_type", "confidence", "new_selector", "reasoning"}
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    valid_types = {"SELECTOR_DRIFT", "LAYOUT_CHANGE", "FUNCTIONAL_REMOVAL", "FUNCTIONAL_CHANGE"}
    assert result["change_type"] in valid_types, f"Unknown change_type: {result['change_type']}"
    assert 0.0 <= result["confidence"] <= 1.0


# ── Accuracy: selector drift ──────────────────────────────────────────────────

async def test_classifies_selector_drift_correctly():
    """Button exists under new ID — must classify as SELECTOR_DRIFT."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "accept_button", "Accept all cookies button", HTML_SELECTOR_DRIFT)

    assert result["change_type"] == "SELECTOR_DRIFT", \
        f"Button clearly exists, expected SELECTOR_DRIFT got {result['change_type']}"
    assert result["confidence"] >= 0.8, \
        f"Expected high confidence on clear drift, got {result['confidence']}"


async def test_selector_drift_provides_new_selector():
    """SELECTOR_DRIFT classification must include a usable new selector."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "accept_button", "Accept all cookies button", HTML_SELECTOR_DRIFT)

    if result["change_type"] == "SELECTOR_DRIFT":
        assert result["new_selector"] is not None, \
            "SELECTOR_DRIFT must provide new_selector"
        assert len(result["new_selector"]) > 0


# ── Safety gate: functional removal ──────────────────────────────────────────

async def test_classifies_functional_removal():
    """No consent buttons present — must classify as FUNCTIONAL_REMOVAL, not SELECTOR_DRIFT."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "reject_button", "Reject all non-essential cookies button", HTML_FUNCTIONAL_REMOVAL)

    assert result["change_type"] == "FUNCTIONAL_REMOVAL", \
        f"CRITICAL: no button in HTML, must be FUNCTIONAL_REMOVAL not {result['change_type']}"


async def test_functional_removal_no_selector():
    """FUNCTIONAL_REMOVAL must never return a new selector — healing would mask regression."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "reject_button", "Reject all non-essential cookies button", HTML_FUNCTIONAL_REMOVAL)

    if result["change_type"] == "FUNCTIONAL_REMOVAL":
        assert not result.get("new_selector"), \
            "CRITICAL: FUNCTIONAL_REMOVAL must not provide new_selector"


# ── Accuracy: functional change ───────────────────────────────────────────────

async def test_classifies_functional_change():
    """Reject path now requires extra clicks — must classify as FUNCTIONAL_CHANGE or FUNCTIONAL_REMOVAL."""
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "reject_button", "Reject all non-essential cookies button", HTML_FUNCTIONAL_CHANGE)

    assert result["change_type"] in ("FUNCTIONAL_CHANGE", "FUNCTIONAL_REMOVAL"), \
        f"Reject removed from banner, expected FUNCTIONAL_CHANGE/REMOVAL got {result['change_type']}"


# ── Confidence calibration ────────────────────────────────────────────────────

async def test_low_confidence_on_ambiguous_html():
    """Ambiguous HTML (no consent context) should yield lower confidence."""
    ambiguous_html = "<div><button>Submit</button><button>Cancel</button></div>"
    agent = SelfHealingAgent()
    result = await agent._classify_failure(
        "accept_button", "Accept all cookies button", ambiguous_html)

    # Either low confidence OR functional removal — both are acceptable safe responses
    is_safe = (
        result["confidence"] < 0.85 or
        result["change_type"] in ("FUNCTIONAL_REMOVAL", "FUNCTIONAL_CHANGE")
    )
    assert is_safe, \
        f"Ambiguous HTML should yield low confidence or functional removal, " \
        f"got change_type={result['change_type']} confidence={result['confidence']}"
