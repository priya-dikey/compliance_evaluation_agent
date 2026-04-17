"""
tests/evals/fixtures.py
Golden-dataset fixtures for agent capability evals.
Each fixture represents a known state — use to assert agents produce correct output.
"""

# ── Compliance fixtures ───────────────────────────────────────────────────────

# Clear GDPR violations: pre-consent cookies, no reject button, bad contrast
FAILING_BANNER = {
    "cmp_name": "Test CMP",
    "banner_format": "modal",
    "pre_consent_cookies": {"_ga": "GA1.2.123456.789", "_fbp": "fb.1.123.456"},
    "reject_button_found": False,
    "accept_button_found": True,
    "contrast_ratios": {
        "reject_ratio": 1.8,
        "accept_ratio": 5.2,
        "ratio_diff":   3.4,
        "wcag_aa_reject": False,
        "wcag_aa_accept": True,
    },
    "consent_mode_v2": {"detected": True, "ad_storage_default_denied": False},
    "fourth_parties": {"fourth_parties": ["pixel.facebook.net"]},
    "banner_facts": {
        "role": None,
        "ariaModal": None,
        "ariaLabel": None,
        "headings": ["We use cookies"],
        "buttons": [
            {"tag": "button", "text": "Accept All", "role": "button",
             "ariaLabel": None, "tabIndex": "0"},
        ],
        "checkboxes": [],
        "links": [{"tag": "a", "text": "Privacy Policy"}],
    },
    "screenshot_b64": None,
}

# Clean banner: GDPR compliant
PASSING_BANNER = {
    "cmp_name": "Cookiebot",
    "banner_format": "modal",
    "pre_consent_cookies": {},
    "reject_button_found": True,
    "accept_button_found": True,
    "contrast_ratios": {
        "reject_ratio": 5.1,
        "accept_ratio": 5.3,
        "ratio_diff":   0.2,
        "wcag_aa_reject": True,
        "wcag_aa_accept": True,
    },
    "consent_mode_v2": {"detected": True, "ad_storage_default_denied": True},
    "fourth_parties": {"fourth_parties": []},
    "banner_facts": {
        "role": "dialog",
        "ariaModal": "true",
        "ariaLabel": "Cookie consent",
        "headings": ["Cookie Consent"],
        "buttons": [
            {"tag": "button", "text": "Accept All",
             "role": "button", "ariaLabel": "Accept all cookies", "tabIndex": "0"},
            {"tag": "button", "text": "Reject All",
             "role": "button", "ariaLabel": "Reject all cookies", "tabIndex": "0"},
            {"tag": "button", "text": "Preferences",
             "role": "button", "ariaLabel": "Cookie preferences", "tabIndex": "0"},
        ],
        "checkboxes": [
            {"label": "Necessary",  "checked": True,  "disabled": True},
            {"label": "Analytics",  "checked": False, "disabled": False},
            {"label": "Marketing",  "checked": False, "disabled": False},
        ],
        "links": [{"tag": "a", "text": "Privacy Policy"}],
    },
    "screenshot_b64": None,
}

# ── Accessibility fixtures ────────────────────────────────────────────────────

AXE_VIOLATIONS_KEYBOARD = [
    {
        "id": "scrollable-region-focusable",
        "impact": "serious",
        "description": "Scrollable region must be keyboard accessible",
        "nodes": 1,
    },
    {
        "id": "focus-trap",
        "impact": "critical",
        "description": "Focus is not trapped within dialog",
        "nodes": 1,
    },
]

AXE_VIOLATIONS_CLEAN = []

# ── Self-healing fixtures ─────────────────────────────────────────────────────

# HTML where the accept button exists under a new selector (selector drift)
HTML_SELECTOR_DRIFT = """
<div id="cookie-consent-banner">
  <h2>We use cookies</h2>
  <button id="new-accept-2024" data-action="accept-all">Accept All Cookies</button>
  <button id="new-decline-2024" data-action="decline-all">Decline All</button>
  <a href="/privacy">Privacy Policy</a>
</div>
"""

# HTML where no consent buttons exist at all (functional removal)
HTML_FUNCTIONAL_REMOVAL = """
<div id="cookie-info">
  <p>This site uses cookies. By continuing to browse you agree to our use of cookies.</p>
  <a href="/privacy">Learn more</a>
</div>
"""

# HTML where the reject path now requires extra clicks (functional change)
HTML_FUNCTIONAL_CHANGE = """
<div id="cookie-banner">
  <button id="accept-btn">Accept All</button>
  <a href="/cookie-settings">Manage cookie settings</a>
</div>
"""

# ── GDPR compliance rules (used across all compliance tests) ─────────────────

GDPR_RULES = {
    "prior_blocking_required": True,
    "explicit_consent_required": True,
    "reject_button_required": True,
    "equal_choice_required": True,
    "granular_consent_required": True,
    "consent_withdrawal_required": True,
    "consent_mode_v2_required": False,
}
