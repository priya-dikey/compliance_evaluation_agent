"""
config/compliance_rules.py
Fetch cookie-banner compliance rules from secureprivacy.ai
with explicit fallback chain. Never fabricates rules.
"""

import httpx
from bs4 import BeautifulSoup

SOURCES = [
    {
        "name": "secureprivacy.ai",
        "urls": [
            "https://secureprivacy.ai/blog/cookie-consent-requirements",
            "https://secureprivacy.ai/blog/gdpr-cookie-consent",
            "https://secureprivacy.ai/resources",
        ],
        "keywords": ["prior blocking", "reject", "consent", "cookie",
                     "gdpr", "opt-in", "dark pattern", "granular"]
    },
    {
        "name": "gdpr.eu",
        "urls": ["https://gdpr.eu/cookies/"],
        "keywords": ["consent", "cookie", "opt-in", "reject"]
    },
    {
        "name": "ico.org.uk",
        "urls": [
            "https://ico.org.uk/for-organisations/direct-marketing-and-privacy/"
            "cookies-and-similar-technologies/"
        ],
        "keywords": ["consent", "cookie", "prior", "reject"]
    },
]

# Hardcoded rule defaults derived from GDPR Art.4(11), Art.7,
# Recital 32, ePrivacy Directive Art.5(3), EDPB Guidelines 05/2020
RULE_DEFAULTS = {
    "prior_blocking_required": True,
    "explicit_consent_required": True,
    "reject_button_required": True,
    "equal_choice_required": True,
    "granular_consent_required": True,
    "consent_withdrawal_required": True,
    "consent_mode_v2_required": False,
    "pre_ticked_boxes_forbidden": True,
    "implied_consent_forbidden": True,
    "consent_valid_duration_months": 12,
}

RULE_SIGNALS = {
    "prior_blocking_required": [
        "cookies must not", "prior to consent", "before consent",
        "block", "prevent loading"
    ],
    "explicit_consent_required": [
        "opt-in", "explicit consent", "affirmative action",
        "clear affirmative"
    ],
    "reject_button_required": [
        "reject", "decline", "refuse", "opt-out option",
        "as easy to withdraw"
    ],
    "equal_choice_required": [
        "equal prominence", "same ease", "dark pattern",
        "equally easy"
    ],
    "granular_consent_required": [
        "granular", "purpose", "specific consent",
        "separate consent", "unbundled"
    ],
    "consent_withdrawal_required": [
        "withdraw consent", "revoke", "change preferences",
        "as easy to withdraw"
    ],
    "pre_ticked_boxes_forbidden": [
        "pre-ticked", "pre-checked", "already ticked",
        "not valid"
    ],
}


async def fetch_compliance_rules() -> dict:
    """
    Attempt to fetch compliance guidance from source chain.
    Returns rules dict, source URLs used, and any error.
    Never fabricates rules — falls back to hardcoded GDPR defaults.
    """
    rules = dict(RULE_DEFAULTS)
    sources_used = []
    errors_encountered = []

    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "QA-Compliance-Agent/1.0"}
    ) as client:
        for source in SOURCES:
            for url in source["urls"]:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        text = _extract_text(resp.text)
                        extracted = _extract_rules(text)
                        # Only update if we found signals — never overwrite
                        # with empty/null
                        for k, v in extracted.items():
                            if v is not None:
                                rules[k] = v
                        sources_used.append(url)
                        print(f"  [compliance] Fetched: {url}")
                        break  # got one URL from this source, move on
                except Exception as e:
                    errors_encountered.append(f"{url}: {e}")
                    continue

            if sources_used:
                break  # got at least one source — stop

    if not sources_used:
        msg = (
            "Could not fetch compliance rules from any source. "
            f"URLs attempted: {[u for s in SOURCES for u in s['urls']]}. "
            "Errors: " + "; ".join(errors_encountered)
        )
        # Still return hardcoded defaults — they are authoritative GDPR rules
        # but flag that no live source was confirmed
        print(f"  [compliance] WARNING: {msg}")
        print("  [compliance] Using hardcoded GDPR defaults (authoritative)")
        return {
            "rules": rules,
            "sources": ["hardcoded_gdpr_defaults"],
            "error": None,  # not a fatal error — defaults are valid
            "warning": msg,
        }

    return {
        "rules": rules,
        "sources": sources_used,
        "error": None,
        "warning": None,
    }


def _extract_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text(" ", strip=True).lower()
    except Exception:
        return html.lower()


def _extract_rules(text: str) -> dict:
    """
    Signal-based rule extraction.
    Returns None for rules where no signal found
    (caller keeps existing default).
    """
    extracted = {}
    for rule, signals in RULE_SIGNALS.items():
        if any(sig in text for sig in signals):
            extracted[rule] = True
    return extracted
