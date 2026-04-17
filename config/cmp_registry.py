"""
config/cmp_registry.py
CMP registry — defines selectors, patterns and detection rules
for known CMPs and custom implementations.

To add a new site:
1. Add a CMP profile to CMP_PROFILES (if CMP not already there)
2. Add a SITE entry pointing to that profile
3. Run: python config/cmp_registry.py --url https://yoursite.com to auto-detect
"""

from dataclasses import dataclass, field
from typing import Optional
import re
from urllib.parse import urlparse


def _normalize_host(host: str) -> str:
    return re.sub(r'^www\d*\.', '', host)


# ── CMP Profile ───────────────────────────────────────────────────────────────

# Banner format constants
FORMAT_BANNER  = "banner"   # fixed/sticky strip, < 40% viewport height
FORMAT_MODAL   = "modal"    # centered dialog with backdrop, role=dialog
FORMAT_OVERLAY = "overlay"  # fullscreen, covers >= 80% viewport
FORMAT_UNKNOWN = "unknown"


@dataclass
class CMPProfile:
    name: str
    accept_selectors: list
    reject_selectors: list
    preferences_selectors: list
    banner_selectors: list        # strip/bar format selectors
    modal_selectors: list         # centered dialog format selectors
    overlay_selectors: list       # fullscreen overlay format selectors
    script_patterns: list         # URL patterns that identify this CMP loading
    cookie_name_patterns: list    # consent cookie names this CMP sets
    consent_mode_v2: bool = False
    notes: str = ""


# ── Known CMP profiles ────────────────────────────────────────────────────────

CMP_PROFILES: dict[str, CMPProfile] = {

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
        preferences_selectors=[
            "#CybotCookiebotDialogBodyButtonDetails",
            "[data-cookiebotdialogbodybuttondetails]",
        ],
        banner_selectors=[
            "#CybotCookiebotDialog",
            "#cookiebanner",
        ],
        modal_selectors=[
            "#CybotCookiebotDialogBodyUnderlay",
            ".CybotCookiebotDialogActive[role='dialog']",
        ],
        overlay_selectors=[],   # Cookiebot does not use full-screen overlay
        script_patterns=[
            "consent.cookiebot.com",
            "cookiebot.com/uc.js",
        ],
        cookie_name_patterns=["CookieConsent"],
        consent_mode_v2=True,
        notes="Cookiebot by Usercentrics. Renders as banner or modal. CBID extracted dynamically.",
    ),

    "onetrust": CMPProfile(
        name="OneTrust",
        accept_selectors=[
            "#onetrust-accept-btn-handler",
            ".onetrust-accept-btn-handler",
        ],
        reject_selectors=[
            "#onetrust-reject-all-handler",
            ".onetrust-reject-all-handler",
        ],
        preferences_selectors=[
            "#onetrust-pc-btn-handler",
            ".onetrust-pc-btn-handler",
            "#onetrust-cookie-policy-video-wrapper",
        ],
        banner_selectors=[
            "#onetrust-banner-sdk",
        ],
        modal_selectors=[
            "#onetrust-pc-sdk",                  # preference centre modal
            ".onetrust-pc-dark-filter",           # modal backdrop
            "#onetrust-consent-sdk[role='dialog']",
        ],
        overlay_selectors=[
            "#onetrust-consent-sdk.ot-fade-in",   # full-screen fade-in variant
        ],
        script_patterns=[
            "cdn.cookielaw.org",
            "optanon.blob.core.windows.net",
        ],
        cookie_name_patterns=["OptanonConsent", "OptanonAlertBoxClosed"],
        consent_mode_v2=True,
        notes="OneTrust / Optanon. Can render as banner, modal, or overlay depending on config.",
    ),

    "trustarc": CMPProfile(
        name="TrustArc",
        accept_selectors=[
            ".trustarc-agree-btn",
            "[data-gtm-trustarc='agree']",
            "a.required.btn-primary",
        ],
        reject_selectors=[
            ".trustarc-decline-btn",
            "[data-gtm-trustarc='decline']",
            "a.required.btn-secondary",
        ],
        preferences_selectors=[
            ".trustarc-manage-btn",
            "a.preferences",
        ],
        banner_selectors=[
            "#truste-consent-track",
            ".trustarc-banner",
        ],
        modal_selectors=[
            "#trustarc-banner-overlay",           # TrustArc modal overlay
            ".truste_overlay",
            "#truste-consent-required",
        ],
        overlay_selectors=[
            "#truste-show-consent",               # full-screen consent wall
        ],
        script_patterns=[
            "consent.trustarc.com",
            "truste.com/notice",
        ],
        cookie_name_patterns=["notice_gdpr_prefs", "notice_preferences", "cmapi_cookie_privacy"],
        consent_mode_v2=False,
        notes="TrustArc (formerly TRUSTe). Modal variant common on US sites.",
    ),

    "quantcast": CMPProfile(
        name="Quantcast",
        accept_selectors=[
            "[data-tracking-opt-in-accept]",
            ".qc-cmp2-summary-buttons button:first-child",
        ],
        reject_selectors=[
            "[data-tracking-opt-in-reject]",
            ".qc-cmp2-summary-buttons button:last-child",
        ],
        preferences_selectors=[
            "[data-tracking-opt-in-preferences]",
            ".qc-cmp2-summary-buttons button:nth-child(2)",
        ],
        banner_selectors=[
            "#qc-cmp2-ui",
            ".qc-cmp2-container",
        ],
        modal_selectors=[
            ".qc-cmp2-main[role='dialog']",
            ".qc-cmp2-backdrop",
        ],
        overlay_selectors=[
            "#qc-cmp2-persistent-link",           # full-screen consent gate variant
        ],
        script_patterns=[
            "quantcast.mgr.consensu.org",
            "cmp.quantcast.com",
        ],
        cookie_name_patterns=["euconsent-v2", "addtl_consent"],
        consent_mode_v2=False,
        notes="Quantcast Choice CMP. Typically renders as banner.",
    ),

    "hm_custom": CMPProfile(
        name="H&M Custom CMP",
        accept_selectors=[
            "[data-testid='cookie-accept-all']",
            "[class*='cookie'][class*='accept']",
            "button[data-consent='accept']",
        ],
        reject_selectors=[
            "[data-testid='cookie-decline-all']",
            "[class*='cookie'][class*='decline']",
            "button[data-consent='decline']",
        ],
        preferences_selectors=[
            "[data-testid='cookie-settings']",
            "[class*='cookie'][class*='settings']",
            "button[data-consent='settings']",
        ],
        banner_selectors=[
            "cookie-banner-hm",
            "[class*='cookie-banner']",
            "[id*='cookie-banner']",
            "[data-testid*='cookie-banner']",
        ],
        modal_selectors=[
            "[data-testid='cookie-modal']",
            "[class*='cookie-modal']",
            "[class*='cookie'][role='dialog']",
        ],
        overlay_selectors=[
            "[data-testid='cookie-overlay']",
            "[class*='cookie-overlay']",
        ],
        script_patterns=[
            "turbocookie.hmgroup.com",
            "hm.com/api/cookie",
        ],
        cookie_name_patterns=["hm-cookie-consent", "consent_hm"],
        consent_mode_v2=False,
        notes="H&M Group custom CMP via turbocookie.hmgroup.com.",
    ),

    "usercentrics": CMPProfile(
        name="Usercentrics",
        accept_selectors=[
            "[data-testid='uc-accept-all-button']",
            "#usercentrics-root button[data-testid='accept']",
        ],
        reject_selectors=[
            "[data-testid='uc-deny-all-button']",
            "#usercentrics-root button[data-testid='deny']",
        ],
        preferences_selectors=[
            "[data-testid='uc-customize-button']",
            "#usercentrics-root button[data-testid='more-information']",
        ],
        banner_selectors=[
            "#usercentrics-root",
            "uc-ui-cmp",
        ],
        modal_selectors=[
            "uc-ui-cmp[layer='FIRST']",           # Usercentrics first layer modal
            "#usercentrics-root[role='dialog']",
        ],
        overlay_selectors=[
            "uc-ui-cmp[layer='SECOND']",           # Usercentrics full second layer
        ],
        script_patterns=[
            "app.usercentrics.eu",
            "privacy-proxy.usercentrics.eu",
        ],
        cookie_name_patterns=["uc_settings", "uc_user_interaction"],
        consent_mode_v2=True,
        notes="Usercentrics CMP. Uses layered architecture: first layer banner/modal, second layer full settings overlay.",
    ),

    "custom": CMPProfile(
        name="Custom / Unknown CMP",
        accept_selectors=[],
        reject_selectors=[],
        preferences_selectors=[],
        banner_selectors=[
            "[id*='cookie'][id*='banner']",
            "[id*='cookie'][id*='consent']",
            "[class*='cookie-banner']",
            "[class*='consent-banner']",
            "[aria-label*='cookie' i]",
        ],
        modal_selectors=[
            "[role='dialog'][aria-label*='cookie' i]",
            "[role='dialog'][aria-label*='consent' i]",
            "[aria-modal='true'][class*='cookie']",
            "[aria-modal='true'][class*='consent']",
        ],
        overlay_selectors=[
            "[class*='cookie-overlay']",
            "[class*='consent-overlay']",
            "[class*='cookie-wall']",
            "[class*='consent-wall']",
        ],
        script_patterns=[],
        cookie_name_patterns=[],
        consent_mode_v2=False,
        notes="Generic fallback for unknown CMPs. Relies on heuristic selectors.",
    ),
}


# ── Site config ───────────────────────────────────────────────────────────────

@dataclass
class SiteConfig:
    url: str
    cmp: str                          # key into CMP_PROFILES
    extra_tracking_patterns: list = field(default_factory=list)
    notes: str = ""


SITE_CONFIGS: dict[str, SiteConfig] = {
    "en.giesswein.com": SiteConfig(
        url="https://en.giesswein.com/",
        cmp="cookiebot",
        extra_tracking_patterns=[],
        notes="Austrian outdoor brand. Uses Cookiebot.",
    ),
    "www.hm.com": SiteConfig(
        url="https://www.hm.com/",
        cmp="hm_custom",
        extra_tracking_patterns=[
            "turbocookie.hmgroup.com",
            "hmgroup.com",
        ],
        notes="H&M Group. Uses custom CMP via turbocookie.hmgroup.com.",
    ),
}

# Pre-computed for O(1) host lookup without per-call regex
_SITE_INDEX: dict[str, SiteConfig] = {
    _normalize_host(k): cfg for k, cfg in SITE_CONFIGS.items()
}


# ── Global tracking patterns (site-agnostic) ─────────────────────────────────

GLOBAL_NON_ESSENTIAL_PATTERNS = [
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "connect.facebook.net",
    "doubleclick.net",
    "hotjar.com",
    "hubspot.com",
    "intercom.io",
    "mixpanel.com",
    "segment.io",
    "amplitude.com",
    "clarity.ms",
    "bing.com/bat",
    "snap.licdn.com",
    "analytics.twitter.com",
    "tiktok.com/i18n",
]


# ── Format detection ─────────────────────────────────────────────────────────

FORMAT_DETECTION_JS = """
() => {
    const candidates = Array.from(document.querySelectorAll(
        '[role=dialog],[aria-modal],[class*=cookie],[class*=consent],' +
        '[id*=cookie],[id*=consent],[class*=overlay],[class*=modal]'
    ));

    for (const el of candidates) {
        if (window.getComputedStyle(el).display === 'none') continue;
        if (!el.getBoundingClientRect().width) continue;

        const s  = window.getComputedStyle(el);
        const r  = el.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        const isFixed   = s.position === 'fixed' || s.position === 'sticky';
        const isModal   = el.getAttribute('role') === 'dialog' ||
                          el.getAttribute('aria-modal') === 'true';
        const pctWidth  = r.width  / vw;
        const pctHeight = r.height / vh;

        // Overlay: fixed + covers >= 80% of both dimensions
        if (isFixed && pctWidth >= 0.8 && pctHeight >= 0.8) {
            return {format: 'overlay', pctWidth, pctHeight,
                    selector: el.id ? '#'+el.id : el.className.split(' ')[0]};
        }
        // Modal: role=dialog or aria-modal, centered, < 80% coverage
        if (isModal || (pctWidth < 0.95 && pctHeight < 0.8 &&
                        r.left > vw * 0.05 && r.top > vh * 0.05)) {
            return {format: 'modal', pctWidth, pctHeight,
                    selector: el.id ? '#'+el.id : el.className.split(' ')[0]};
        }
        // Banner: fixed/sticky, narrow height (< 40% viewport)
        if (isFixed && pctHeight < 0.4) {
            return {format: 'banner', pctWidth, pctHeight,
                    selector: el.id ? '#'+el.id : el.className.split(' ')[0]};
        }
    }
    return {format: 'unknown', pctWidth: 0, pctHeight: 0, selector: ''};
}
"""


# ── Resolver ──────────────────────────────────────────────────────────────────

def get_config(url: str) -> tuple[SiteConfig, CMPProfile]:
    """Return (SiteConfig, CMPProfile) for a URL. Falls back to generic custom profile."""
    bare_host = _normalize_host(urlparse(url).netloc)
    for bare_key, cfg in _SITE_INDEX.items():
        if bare_host == bare_key or bare_host.endswith('.' + bare_key):
            return cfg, CMP_PROFILES[cfg.cmp]
    generic = SiteConfig(url=url, cmp="custom",
                         notes="Auto-generated — site not in registry")
    return generic, CMP_PROFILES["custom"]


def get_non_essential_patterns(site_cfg: SiteConfig) -> list:
    """Combine global patterns with site-specific extras."""
    return list(set(
        GLOBAL_NON_ESSENTIAL_PATTERNS +
        site_cfg.extra_tracking_patterns +
        CMP_PROFILES[site_cfg.cmp].script_patterns
    ))


def build_selector_strategies(profile: CMPProfile) -> dict:
    """
    Build the SELECTOR_STRATEGIES dict for self_healing.py
    from a CMP profile, with heuristic and Claude fallbacks appended.
    """
    heuristics = {
        "accept_button":      "button:has-text(/accept all|allow all|agree|enable cookies|accept cookies/i)",
        "reject_button":      "button:has-text(/decline|deny|reject all|reject|refuse|only necessary|only essential|use essential cookies/i)",
        "preferences_button": "button:has-text(/preferences|settings|customise|customize|manage/i)",
    }
    return {
        "accept_button": [
            *profile.accept_selectors,
            heuristics["accept_button"],
            None,
        ],
        "reject_button": [
            *profile.reject_selectors,
            heuristics["reject_button"],
            None,
        ],
        "preferences_button": [
            *profile.preferences_selectors,
            heuristics["preferences_button"],
            None,
        ],
    }


# ── Auto-detect CLI ───────────────────────────────────────────────────────────

async def _auto_detect(url: str):
    """
    Load the page, inspect network requests and DOM,
    identify which CMP is in use, and suggest a SiteConfig entry.
    """
    from playwright.async_api import async_playwright

    print(f"\n[cmp_registry] Auto-detecting CMP for: {url}\n")
    detected_scripts = []
    detected_selectors = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("request", lambda r: detected_scripts.append(r.url))
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check DOM for known selectors across all three formats
        for cmp_key, profile in CMP_PROFILES.items():
            if cmp_key == "custom":
                continue
            all_sel = (
                [(s, FORMAT_BANNER)  for s in profile.banner_selectors] +
                [(s, FORMAT_MODAL)   for s in profile.modal_selectors] +
                [(s, FORMAT_OVERLAY) for s in profile.overlay_selectors]
            )
            for sel, fmt in all_sel:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        detected_selectors.append((cmp_key, sel, fmt))
                except Exception:
                    pass

        # Also run JS format detection
        detected_format = await page.evaluate(FORMAT_DETECTION_JS)

        await browser.close()

    # Match scripts against profiles
    matched_cmps = set()
    for script_url in detected_scripts:
        for cmp_key, profile in CMP_PROFILES.items():
            if cmp_key == "custom":
                continue
            for pattern in profile.script_patterns:
                if pattern in script_url:
                    matched_cmps.add(cmp_key)

    print("── Script matches ─────────────────────────────")
    if matched_cmps:
        for m in matched_cmps:
            print(f"  ✓ {CMP_PROFILES[m].name} ({m})")
    else:
        print("  No known CMP scripts detected")

    print("\n── DOM matches ────────────────────────────────")
    if detected_selectors:
        for item in detected_selectors:
            cmp_key, sel, fmt = item
            print(f"  \u2713 {cmp_key} [{fmt}]: {sel}")
    else:
        print("  No known selectors found")

    print(f"\n── Format detection (JS) ──────────────────────")
    print(f"  Format:  {detected_format.get('format', 'unknown')}")
    print(f"  Width:   {detected_format.get('pctWidth', 0):.0%} viewport")
    print(f"  Height:  {detected_format.get('pctHeight', 0):.0%} viewport")

    # Best guess
    best = (matched_cmps | {s[0] for s in detected_selectors})
    best = list(best)[0] if best else "custom"

    host = urlparse(url).netloc.lstrip("www.")
    print(f"\n── Suggested SITE_CONFIGS entry ───────────────")
    print(f"""
    "{host}": SiteConfig(
        url="{url}",
        cmp="{best}",
        extra_tracking_patterns=[],
        notes="Auto-detected",
    ),""")

    # List CMP scripts seen
    cmp_scripts = [s for s in detected_scripts
                   if any(p in s for profile in CMP_PROFILES.values()
                          for p in profile.script_patterns)]
    if cmp_scripts:
        print("\n── CMP script URLs detected ───────────────────")
        for s in set(cmp_scripts):
            print(f"  {s}")


if __name__ == "__main__":
    import sys
    import asyncio

    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        target = sys.argv[idx + 1]
        asyncio.run(_auto_detect(target))
    else:
        print("Usage: python config/cmp_registry.py --url https://yoursite.com")
        print("\nRegistered CMPs:")
        for k, v in CMP_PROFILES.items():
            print(f"  {k:20} {v.name}")
        print("\nRegistered sites:")
        for k, v in SITE_CONFIGS.items():
            print(f"  {k:30} → {v.cmp}")
