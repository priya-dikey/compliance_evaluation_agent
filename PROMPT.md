# Hybrid QA Agent — Claude Code Prompt
**Temperature: 0**

You are an expert QA automation engineer specialising in AI-powered compliance testing.

The system is **site-agnostic** — target URL passed at runtime via --url.  
All CMP-specific configuration lives exclusively in `config/cmp_registry.py`.

---

## 0. Fetch Compliance Rules (MANDATORY)

Fetch from secureprivacy.ai. Fallback chain if unreachable:
1. https://gdpr.eu/cookies/
2. https://ico.org.uk/for-organisations/direct-marketing/cookies-and-similar-technologies/
3. https://edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-052020-consent-under-regulation-2016679_en

Never fabricate rules. Raise explicit error if no source reachable.

```python
compliance_rules = {
    "prior_blocking_required": True,
    "explicit_consent_required": True,
    "reject_button_required": True,
    "equal_choice_required": True,
    "granular_consent_required": True,
    "consent_withdrawal_required": True,
    "consent_mode_v2_required": False,  # only if Google tags detected
}
```

---

## 1. CMP Registry (config/cmp_registry.py)

Single source of truth for all site and CMP configuration.
**Nothing CMP-specific is hardcoded anywhere else.**

### CMPProfile dataclass
```python
@dataclass
class CMPProfile:
    name: str
    accept_selectors: list       # ordered: primary -> secondary
    reject_selectors: list
    preferences_selectors: list
    banner_selectors: list
    script_patterns: list        # URL fragments that identify this CMP
    cookie_name_patterns: list   # consent cookie names set by this CMP
    consent_mode_v2: bool = False
    notes: str = ""
```

### Required CMP_PROFILES entries
Implement all of: cookiebot, onetrust, trustarc, usercentrics, hm_custom, custom

Example entries:
```python
"cookiebot": CMPProfile(
    name="Cookiebot",
    accept_selectors=[
        "#CybotCookiebotDialogBodyButtonAccept",
        "[data-cookiebotdialogbodybuttonaccept]",
    ],
    reject_selectors=[
        "#CybotCookiebotDialogBodyButtonDecline",
        "[data-cookiebotdialogbodybuttondecline]",
    ],
    preferences_selectors=["#CybotCookiebotDialogBodyButtonDetails"],
    banner_selectors=["#CybotCookiebotDialog"],
    script_patterns=["consent.cookiebot.com"],
    cookie_name_patterns=["CookieConsent"],
    consent_mode_v2=True,
),

"hm_custom": CMPProfile(
    name="H&M Custom CMP",
    accept_selectors=["[data-testid='cookie-accept-all']", "[class*='cookie'][class*='accept']"],
    reject_selectors=["[data-testid='cookie-decline-all']", "[class*='cookie'][class*='decline']"],
    preferences_selectors=["[data-testid='cookie-settings']"],
    banner_selectors=["cookie-banner-hm", "[class*='cookie-banner']", "[id*='cookie-banner']"],
    script_patterns=["turbocookie.hmgroup.com", "hm.com/api/cookie"],
    cookie_name_patterns=["hm-cookie-consent"],
    consent_mode_v2=False,
    notes="H&M Group custom CMP via turbocookie.hmgroup.com",
),

"custom": CMPProfile(  # generic fallback — always present
    name="Custom / Unknown CMP",
    accept_selectors=[],
    reject_selectors=[],
    preferences_selectors=[],
    banner_selectors=[
        "[id*='cookie'][id*='banner']",
        "[class*='cookie-banner']",
        "[role='dialog'][aria-label*='cookie' i]",
    ],
    script_patterns=[],
    cookie_name_patterns=[],
),
```

### SiteConfig and SITE_CONFIGS
```python
@dataclass
class SiteConfig:
    url: str
    cmp: str                           # key into CMP_PROFILES
    extra_tracking_patterns: list = field(default_factory=list)
    notes: str = ""

SITE_CONFIGS: dict[str, SiteConfig] = {
    "en.giesswein.com": SiteConfig(url="https://en.giesswein.com/", cmp="cookiebot"),
    "www.hm.com": SiteConfig(
        url="https://www.hm.com/",
        cmp="hm_custom",
        extra_tracking_patterns=["turbocookie.hmgroup.com", "hmgroup.com"],
    ),
}
```

### GLOBAL_NON_ESSENTIAL_PATTERNS (site-agnostic)
```python
GLOBAL_NON_ESSENTIAL_PATTERNS = [
    "google-analytics.com", "googletagmanager.com", "facebook.net",
    "doubleclick.net", "hotjar.com", "hubspot.com", "intercom.io",
    "mixpanel.com", "segment.io", "amplitude.com", "clarity.ms",
]
```

### Registry functions (implement all)
```python
def get_config(url: str) -> tuple[SiteConfig, CMPProfile]:
    """Resolve URL hostname to (SiteConfig, CMPProfile).
    Falls back to 'custom' profile if site not registered. Never raises."""

def get_non_essential_patterns(site_cfg: SiteConfig) -> list:
    """Merge GLOBAL_NON_ESSENTIAL_PATTERNS + site extras + CMP script patterns."""

def build_selector_strategies(profile: CMPProfile) -> dict:
    """Build self_healing.py strategy dict from CMPProfile.
    Appends heuristic regex selectors and None (Claude recovery) automatically.
    Returns:
    {
        "accept_button":      [*profile.accept_selectors, heuristic, None],
        "reject_button":      [*profile.reject_selectors, heuristic, None],
        "preferences_button": [*profile.preferences_selectors, heuristic, None],
    }
    """
```

### Auto-detect CLI
```bash
python config/cmp_registry.py --url https://newsite.com
```
Loads page, intercepts requests, checks DOM, prints the SiteConfig block to paste.
Never modifies the registry — output only.

**Complete workflow to add a new site:**
1. Run auto-detect
2. Paste printed SiteConfig into SITE_CONFIGS
3. Change TARGET_URL in orchestrator.py
4. Nothing else changes

---

## 2. Test Data Layer

Use CMP profile cookie names for correct consent cookie injection per site:

```python
def build_test_contexts(profile: CMPProfile) -> list:
    cookie = profile.cookie_name_patterns[0] if profile.cookie_name_patterns else "consent"
    return [
        {"name": "fresh_visitor",      "cookies": {}},
        {"name": "returning_accepted", "cookies": {cookie: "true"}},
        {"name": "returning_rejected", "cookies": {cookie: "false"}},
        {"name": "expired_consent",    "cookies": {cookie: "true", "consent_date": "2022-01-01"}},
    ]

geo_contexts = [
    {"name": "EU_Germany",    "locale": "de-DE", "timezone": "Europe/Berlin",
     "opt_in_required": True,  "law": "GDPR"},
    {"name": "US_California", "locale": "en-US", "timezone": "America/Los_Angeles",
     "opt_in_required": False, "law": "CCPA"},
]
```

---

## 3. Gherkin Scenarios (features/cookie_consent.feature)

Cover: banner presence, pre-consent tracking, accept, reject, granular,
persistence, expiry, withdrawal, EU/US geo, keyboard nav, screen reader.
Reference compliance_rules from step 0. Use {cmp_name} in Background.

---

## 4. Deterministic Layer (agents/deterministic.py)

Import registry. Never hardcode selectors or patterns.

```python
from config.cmp_registry import get_config, get_non_essential_patterns

class DeterministicAgent:
    def __init__(self, url: str):
        self.url = url
        self.site_cfg, self.cmp_profile = get_config(url)
        self.non_essential_patterns = get_non_essential_patterns(self.site_cfg)
        print(f"  [deterministic] CMP: {self.cmp_profile.name}")
```

Key rules:
- Pre-consent cookie check uses `self.non_essential_patterns`
- Banner detection uses `self.cmp_profile.banner_selectors` first, then generic fallbacks
- Consent Mode v2 validation only runs if `self.cmp_profile.consent_mode_v2 is True`
- CMP script URL extracted from live network requests via `self.cmp_profile.script_patterns`

Fourth party scanner, axe-core, contrast ratio, cross-browser matrix: unchanged.

---

## 5. Self-Healing Layer (agents/self_healing.py)

Selector strategies built from registry at runtime. Never hardcoded.

```python
from config.cmp_registry import build_selector_strategies, CMPProfile

class SelfHealingAgent:
    def __init__(self):
        self._strategies = {          # generic heuristics until set_cmp_profile() called
            "accept_button":      ["button:has-text(/accept all|accept cookies/i)", None],
            "reject_button":      ["button:has-text(/decline|reject|refuse|only necessary/i)", None],
            "preferences_button": ["button:has-text(/preferences|settings|manage/i)", None],
        }

    def set_cmp_profile(self, profile: CMPProfile):
        """Called by orchestrator after CMP resolved. Must be called before find_element()."""
        self._strategies = build_selector_strategies(profile)
```

Failure classification before Claude recovery:
- SELECTOR_DRIFT: auto-heal if confidence >= 0.85
- LAYOUT_CHANGE: heal but flag compliance concern
- FUNCTIONAL_REMOVAL: FAIL, do not heal
- FUNCTIONAL_CHANGE: FAIL, requires test rewrite

No silent passes. Every fallback level logged.

---

## 6. Orchestrator (orchestrator.py)

```python
TARGET_URL = "https://en.giesswein.com/"  # default only — override with --url

async def run(url: str):
    det_agent   = DeterministicAgent(url)     # resolves CMP internally
    self_healer = SelfHealingAgent()
    self_healer.set_cmp_profile(det_agent.cmp_profile)  # share profile
    # ... rest of pipeline unchanged

# Timestamped output so every run produces a unique file:
# reports/report_20260416_061422.json
# reports/report_20260416_061422.html
```

---

## 7. AI Evaluation Layer (agents/ai_evaluators.py)

All Claude calls: temperature=0, structured JSON output only.
Add `"cmp_detected": "{cmp_name}"` to all evaluator prompts.
All other prompt structure unchanged.

---

## 8. Multi-Evaluator Voting (agents/voting.py)

Unchanged. Fully site-agnostic.
Weights: compliance 0.5, accessibility 0.3, ux 0.2.
Compliance veto threshold: score <= 2.

---

## 9. evaluation.py

Unchanged. Fully site-agnostic.
BLOCK requires: critical + confidence >= 0.85 + deterministic evidence.

---

## 10. Error Handling

Never silent-pass. Explicit failure always.
cmp_not_in_registry -> use 'custom' profile, log warning, continue.
auto_detect_no_match -> log unknown CMP, use 'custom' profile, flag in report.
All other strategies unchanged from original spec.

---

## 11. Final Output Format

Same as original spec plus two new meta fields:
```json
"meta": {
    "cmp_detected": "Cookiebot",
    "cmp_profile_key": "cookiebot",
    ...
}
```

---

## 12. Deliverables

1.  config/compliance_rules.py
2.  config/cmp_registry.py          <- NEW: registry, all CMPs, all site configs
3.  features/cookie_consent.feature
4.  agents/deterministic.py         <- updated: registry-driven
5.  agents/self_healing.py          <- updated: registry-driven
6.  agents/ai_evaluators.py
7.  agents/voting.py
8.  evaluation.py
9.  orchestrator.py                 <- updated: set_cmp_profile + timestamped reports
10. reports/generate_report.py      <- NEW: HTML report generator
11. reports/example_output.json

---

## 13. Constraints

- Temperature: 0 on all Claude calls
- Separate facts (Playwright) from reasoning (Claude)
- Never fabricate compliance rules or test results
- No silent passes — explicit failure always
- Log every self-healing event and fallback level
- Structured JSON output from all Claude calls
- Human-review flag for any low-confidence or disagreement finding
- Pipeline BLOCK requires: critical + confidence >= 0.85 + deterministic evidence
- **No CMP-specific selectors outside cmp_registry.py**
- **No hardcoded target URL** — always via --url argument
- **Timestamped report filenames** — every run produces unique files