"""
agents/deterministic.py
Deterministic Playwright test layer.
Separates facts from reasoning — Claude gets measurements, not raw HTML alone.
"""

import asyncio
import base64
import json
import math
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Browser
from playwright_stealth import Stealth

_stealth = Stealth()

from config.cmp_registry import get_config, get_non_essential_patterns, CMP_PROFILES, FORMAT_DETECTION_JS, FORMAT_BANNER, FORMAT_MODAL, FORMAT_OVERLAY, FORMAT_UNKNOWN

AXE_CDN = ("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.3/axe.min.js")

_CHROMIUM_ARGS = ["--disable-blink-features=AutomationControlled"]
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class DeterministicAgent:
    def __init__(self, url: str):
        self.url = url
        self.baseline_path = "reports/baseline.json"
        self.site_cfg, self.cmp_profile = get_config(url)
        self.non_essential_patterns = get_non_essential_patterns(self.site_cfg)
        print(f"  [deterministic] CMP detected: {self.cmp_profile.name}")

    async def run(
        self,
        devices: list,
        contexts: list,
        geo_contexts: list,
        self_healer,
    ) -> dict:
        results = {
            "pre_consent_cookies": {},
            "reject_button_found": False,
            "accept_button_found": False,
            "banner_format":       "unknown",
            "consent_mode_v2":     {},
            "fourth_parties":      {},
            "axe_violations":      [],
            "contrast_ratios":     {},
            "cross_browser":       {},
            "geo_results":         {},
            "primary_context":     {},
            "score":               0.0,
        }

        async with async_playwright() as pw:
            # Primary run: Chromium + fresh visitor
            browser = await pw.chromium.launch(
                headless=True, args=_CHROMIUM_ARGS)
            primary = await self._run_context(
                browser, contexts[0], geo_contexts[0], self_healer,
                device=devices[0]
            )
            results["primary_context"] = primary
            for key, default in {
                "pre_consent_cookies": {},
                "reject_button_found": False,
                "accept_button_found": False,
                "banner_format":       "unknown",
                "consent_mode_v2":     {},
                "fourth_parties":      {},
                "axe_violations":      [],
                "contrast_ratios":     {},
            }.items():
                results[key] = primary.get(key, default)
            await browser.close()

            # Cross-browser + additional geo — run in parallel
            async def _device_run(device):
                try:
                    btype = device["browser"]
                    kw = {"args": _CHROMIUM_ARGS} if btype == "chromium" else {}
                    b = await getattr(pw, btype).launch(headless=True, **kw)
                    try:
                        r = await self._run_context(
                            b, contexts[0], geo_contexts[0], self_healer, device=device)
                    finally:
                        await b.close()
                    results["cross_browser"][device["name"]] = {
                        "banner_found":        r.get("banner_found"),
                        "banner_format":       r.get("banner_format", "unknown"),
                        "reject_found":        r.get("reject_button_found"),
                        "pre_consent_cookies": r.get("pre_consent_cookies", {}),
                        "screenshot_b64":      r.get("screenshot_b64"),
                    }
                except Exception as e:
                    results["cross_browser"][device["name"]] = {"error": str(e)}

            async def _geo_run(geo):
                try:
                    b = await pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
                    try:
                        r = await self._run_context(
                            b, contexts[0], geo, self_healer, device=devices[0])
                    finally:
                        await b.close()
                    results["geo_results"][geo["name"]] = {
                        "banner_found":    r.get("banner_found"),
                        "opt_in_required": geo["opt_in_required"],
                        "banner_html":     r.get("banner_html", ""),
                        "screenshot_b64":  r.get("screenshot_b64"),
                    }
                except Exception as e:
                    results["geo_results"][geo["name"]] = {"error": str(e)}

            # Context checks — banner presence for returning/expired users
            context_checks: dict = {}

            async def _context_check(test_ctx):
                b = await pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
                try:
                    ctx = await b.new_context(
                        viewport={"width": 1280, "height": 800},
                        locale=geo_contexts[0].get("locale", "en-US"),
                    )
                    if test_ctx.get("cookies"):
                        await ctx.add_cookies([
                            {"name": k, "value": v,
                             "domain": self._domain(), "path": "/"}
                            for k, v in test_ctx["cookies"].items()
                        ])
                    page = await ctx.new_page()
                    await _stealth.apply_stealth_async(page)
                    await page.goto(
                        self.url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(1500)
                    banner, _ = await self._find_banner(page)
                    context_checks[test_ctx["name"]] = {
                        "banner_found": banner is not None}
                    await ctx.close()
                except Exception as e:
                    context_checks[test_ctx["name"]] = {
                        "error": str(e), "banner_found": None}
                finally:
                    await b.close()

            # Interaction tests — post-reject/accept, prefs panel, withdrawal
            interaction_checks: dict = {}

            async def _interaction_tests():
                b = await pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
                try:
                    ic = await self._run_interaction_tests(
                        b, geo_contexts[0], self_healer, devices[0])
                    interaction_checks.update(ic)
                except Exception as e:
                    print(f"  [deterministic] Interaction tests error: {e}")
                finally:
                    await b.close()

            await asyncio.gather(
                *[_device_run(d) for d in devices[1:]],
                *[_geo_run(g) for g in geo_contexts[1:]],
                *[_context_check(c) for c in contexts[1:]],
                _interaction_tests(),
            )

        results["score"] = self._compute_score(results)
        results["context_checks"] = context_checks
        results["interaction_checks"] = interaction_checks
        return results

    async def _run_context(
        self, browser: Browser, context: dict,
        geo: dict, self_healer, device: dict
    ) -> dict:
        viewport = device.get("viewport") or {"width": 1280, "height": 800}
        ctx = await browser.new_context(
            viewport=viewport,
            locale=geo.get("locale", "en-US"),
            timezone_id=geo.get("timezone", "UTC"),
            is_mobile=device.get("is_mobile", False),
            user_agent=device.get("user_agent", _DEFAULT_UA),
        )

        # Inject prior cookies if context specifies them
        if context.get("cookies"):
            cookies = [
                {"name": k, "value": v, "domain": self._domain(),
                 "path": "/"}
                for k, v in context["cookies"].items()
            ]
            await ctx.add_cookies(cookies)

        page = await ctx.new_page()
        await _stealth.apply_stealth_async(page)

        # Track requests before consent
        pre_consent_requests = []
        request_log = []

        def on_request(req):
            request_log.append({
                "url": req.url,
                "time": time.time(),
                "initiator": req.headers.get("referer", "direct"),
            })

        page.on("request", on_request)

        # Track dataLayer for Consent Mode v2
        await page.add_init_script("""
            window.__consentPushes = [];
            window.dataLayer = window.dataLayer || [];
            const origPush = window.dataLayer.push.bind(window.dataLayer);
            window.dataLayer.push = function(...args) {
                window.__consentPushes.push(JSON.parse(JSON.stringify(args)));
                return origPush(...args);
            };
        """)

        consent_click_time = None
        result = {
            "device":               device["name"],
            "geo":                  geo["name"],
            "context":              context["name"],
            "banner_found":         False,
            "banner_format":        FORMAT_UNKNOWN,
            "banner_html":          "",
            "screenshot_b64":       "",
            "pre_consent_cookies":  {},
            "reject_button_found":  False,
            "accept_button_found":  False,
            "consent_mode_v2":      {},
            "fourth_parties":       {},
            "axe_violations":       [],
            "contrast_ratios":      {},
        }

        try:
            await page.goto(self.url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Screenshot before any interaction
            screenshot = await page.screenshot(full_page=False)
            result["screenshot_b64"] = base64.b64encode(
                screenshot).decode()

            # Check cookies before consent click
            cookies_before = await ctx.cookies()
            pre_consent = {
                c["name"]: c["value"] for c in cookies_before
                if any(p in c.get("domain", "") or p in c["name"].lower()
                       for p in self.non_essential_patterns)
            }
            result["pre_consent_cookies"] = pre_consent

            # Find banner and detect its format
            banner, banner_format = await self._find_banner(page)
            if banner:
                result["banner_found"]  = True
                result["banner_format"] = banner_format
                result["banner_html"]   = await banner.inner_html()
                result["banner_facts"]  = await self._extract_banner_facts(page, banner)
                print(f"  [deterministic] Banner found: format={banner_format}")

            # Find buttons via self-healer
            reject_el = await self_healer.find_element(
                page, "reject_button",
                "Reject/decline all non-essential cookies button"
            )
            accept_el = await self_healer.find_element(
                page, "accept_button",
                "Accept all cookies button"
            )
            result["reject_button_found"] = reject_el is not None
            result["accept_button_found"] = accept_el is not None

            # Contrast ratios
            if reject_el and accept_el:
                result["contrast_ratios"] = await self._measure_contrast(
                    page, reject_el, accept_el)

            # Consent Mode v2
            consent_pushes = await page.evaluate(
                "() => window.__consentPushes")
            result["consent_mode_v2"] = self._parse_consent_mode(
                consent_pushes)

            # Fourth party scan
            result["fourth_parties"] = self._scan_fourth_parties(
                request_log)

            # Axe-core on banner
            result["axe_violations"] = await self._run_axe(page)

        except Exception as e:
            result["error"] = str(e)
            print(f"  [deterministic] Error in context {context['name']}: {e}")

        await ctx.close()
        return result

    async def _run_interaction_tests(
        self, browser, geo: dict, self_healer, device: dict
    ) -> dict:
        """
        Run post-reject, post-accept, granular-prefs, and withdrawal checks
        in parallel, each in its own browser context.
        Returns dict: {post_reject, post_accept, granular_prefs, withdrawal}
        """
        viewport = device.get("viewport") or {"width": 1280, "height": 800}
        _CMV2_SCRIPT = """
            window.__consentPushes = [];
            window.dataLayer = window.dataLayer || [];
            const _orig = window.dataLayer.push.bind(window.dataLayer);
            window.dataLayer.push = function(...a) {
                window.__consentPushes.push(JSON.parse(JSON.stringify(a)));
                return _orig(...a);
            };
        """

        async def _make_page(extra_cookies=None):
            ctx = await browser.new_context(
                viewport=viewport,
                locale=geo.get("locale", "en-US"),
                timezone_id=geo.get("timezone", "UTC"),
                user_agent=_DEFAULT_UA,
            )
            if extra_cookies:
                await ctx.add_cookies([
                    {"name": k, "value": v,
                     "domain": self._domain(), "path": "/"}
                    for k, v in extra_cookies.items()
                ])
            page = await ctx.new_page()
            await _stealth.apply_stealth_async(page)
            await page.add_init_script(_CMV2_SCRIPT)
            return ctx, page

        results: dict = {}

        async def _post_reject():
            ctx, page = await _make_page()
            try:
                await page.goto(
                    self.url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                reject_el = await self_healer.find_element(
                    page, "reject_button",
                    "Reject all non-essential cookies button")
                if not reject_el:
                    results["post_reject"] = {
                        "reject_found": False, "banner_dismissed": False,
                        "post_reject_cookies": {}, "cmv2_ad_denied": False}
                    return
                await reject_el.click()
                await page.wait_for_timeout(2000)
                banner_after, _ = await self._find_banner(page)
                cookies = await ctx.cookies()
                tracking = {
                    c["name"]: c["value"] for c in cookies
                    if any(p in c.get("domain", "") or p in c["name"].lower()
                           for p in self.non_essential_patterns)
                }
                pushes = await page.evaluate(
                    "() => window.__consentPushes || []")
                cmv2 = self._parse_consent_mode(pushes)
                update_str = str(cmv2.get("update_pushes", "")).lower()
                results["post_reject"] = {
                    "reject_found":      True,
                    "banner_dismissed":  banner_after is None,
                    "post_reject_cookies": tracking,
                    "cmv2_ad_denied":    "denied" in update_str,
                }
            except Exception as e:
                results["post_reject"] = {"error": str(e)}
            finally:
                await ctx.close()

        async def _post_accept():
            ctx, page = await _make_page()
            try:
                await page.goto(
                    self.url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                accept_el = await self_healer.find_element(
                    page, "accept_button", "Accept all cookies button")
                if not accept_el:
                    results["post_accept"] = {
                        "accept_found": False, "post_accept_cookies": {},
                        "cmv2_analytics_granted": False,
                        "cmv2_ad_still_denied": False}
                    return
                await accept_el.click()
                await page.wait_for_timeout(2000)
                cookies = await ctx.cookies()
                analytics = {
                    c["name"]: c["value"] for c in cookies
                    if any(p in c.get("domain", "") or p in c["name"].lower()
                           for p in self.non_essential_patterns)
                }
                pushes = await page.evaluate(
                    "() => window.__consentPushes || []")
                cmv2 = self._parse_consent_mode(pushes)
                update_str = str(cmv2.get("update_pushes", "")).lower()
                results["post_accept"] = {
                    "accept_found":           True,
                    "post_accept_cookies":    analytics,
                    "cmv2_analytics_granted": (
                        "analytics_storage" in update_str
                        and "granted" in update_str
                    ),
                    "cmv2_ad_still_denied": (
                        "ad_storage" in update_str
                        and "denied" in update_str
                    ),
                }
            except Exception as e:
                results["post_accept"] = {"error": str(e)}
            finally:
                await ctx.close()

        async def _granular_prefs():
            ctx, page = await _make_page()
            try:
                await page.goto(
                    self.url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                prefs_el = await self_healer.find_element(
                    page, "preferences_button",
                    "Cookie preferences or settings button")
                if not prefs_el:
                    results["granular_prefs"] = {
                        "panel_opened": False,
                        "categories": [], "optional_prechecked": []}
                    return
                await prefs_el.click()
                await page.wait_for_timeout(2000)
                panel = None
                for sel in [
                    "[role='dialog']", "[class*='preference']",
                    "[class*='setting']", "[id*='preference']",
                    "[id*='setting']",
                ]:
                    el = await self._try_visible(page, sel)
                    if el:
                        panel = el
                        break
                if not panel:
                    results["granular_prefs"] = {
                        "panel_opened": False,
                        "categories": [], "optional_prechecked": []}
                    return
                handle = await panel.element_handle()
                panel_data = await page.evaluate("""
                    (el) => {
                        const boxes   = Array.from(
                            el.querySelectorAll('input[type="checkbox"]'));
                        const toggles = Array.from(
                            el.querySelectorAll('[role="switch"]'));
                        return [...boxes, ...toggles].map(e => ({
                            label: (
                                e.labels?.[0]?.innerText ||
                                e.getAttribute('aria-label') ||
                                e.closest('[class*="category"]')
                                    ?.querySelector('h2,h3,h4,label')
                                    ?.innerText || ''
                            ).trim().slice(0, 80),
                            checked:  e.checked ||
                                      e.getAttribute('aria-checked') === 'true',
                            disabled: e.disabled ||
                                      e.getAttribute('aria-disabled') === 'true',
                        })).filter(c => c.label);
                    }
                """, handle)
                categories       = [c["label"] for c in panel_data]
                optional_ticked  = [
                    c["label"] for c in panel_data
                    if c["checked"] and not c["disabled"]
                       and "necessary" not in c["label"].lower()
                ]
                results["granular_prefs"] = {
                    "panel_opened":      True,
                    "categories":        categories,
                    "optional_prechecked": optional_ticked,
                }
            except Exception as e:
                results["granular_prefs"] = {
                    "error": str(e), "panel_opened": False}
            finally:
                await ctx.close()

        async def _withdrawal():
            ctx, page = await _make_page(
                extra_cookies={"CookieConsent": "true"})
            try:
                await page.goto(
                    self.url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                pref_link = None
                for sel in [
                    "a:has-text(/cookie settings|cookie preferences|privacy settings|manage cookies/i)",
                    "button:has-text(/cookie settings|cookie preferences|manage cookies/i)",
                    "[class*='cookie-settings']",
                    "[id*='cookie-settings']",
                    "[class*='privacy-settings']",
                    "a:has-text(/manage consent|consent settings/i)",
                ]:
                    el = await self._try_visible(page, sel)
                    if el:
                        pref_link = el
                        break
                if not pref_link:
                    results["withdrawal"] = {
                        "preferences_link_found": False,
                        "panel_opened": False}
                    return
                await pref_link.click()
                await page.wait_for_timeout(2000)
                panel_visible = False
                for sel in [
                    "[role='dialog']", "[class*='preference']",
                    "[class*='cookie-modal']", "[id*='cookie']",
                ]:
                    el = await self._try_visible(page, sel)
                    if el:
                        panel_visible = True
                        break
                results["withdrawal"] = {
                    "preferences_link_found": True,
                    "panel_opened":           panel_visible,
                }
            except Exception as e:
                results["withdrawal"] = {
                    "error": str(e), "preferences_link_found": False}
            finally:
                await ctx.close()

        await asyncio.gather(
            _post_reject(), _post_accept(),
            _granular_prefs(), _withdrawal(),
        )
        return results

    async def _find_banner(self, page: Page) -> tuple:
        """
        Returns (element, format) where format is one of:
        FORMAT_BANNER | FORMAT_MODAL | FORMAT_OVERLAY | FORMAT_UNKNOWN

        Try CMP-specific selectors per format first, then generic fallbacks,
        then JS-based format detection as last resort.
        """
        # 1. Try CMP-specific selectors in format order
        format_selector_map = [
            (FORMAT_BANNER,  self.cmp_profile.banner_selectors),
            (FORMAT_MODAL,   self.cmp_profile.modal_selectors),
            (FORMAT_OVERLAY, self.cmp_profile.overlay_selectors),
        ]
        for fmt, selectors in format_selector_map:
            for sel in selectors:
                el = await self._try_visible(page, sel)
                if el:
                    return el, fmt

        # 2. Generic fallbacks per format
        generic_map = [
            (FORMAT_BANNER, [
                "[id*='cookie'][id*='banner']",
                "[id*='cookie'][id*='consent']",
                "[class*='cookie-banner']",
                "[class*='consent-bar']",
                "[aria-label*='cookie' i]",
            ]),
            (FORMAT_MODAL, [
                "[role='dialog'][aria-label*='cookie' i]",
                "[role='dialog'][aria-label*='consent' i]",
                "[aria-modal='true'][class*='cookie']",
                "[aria-modal='true'][class*='consent']",
                "[class*='cookie-modal']",
                "[class*='consent-modal']",
            ]),
            (FORMAT_OVERLAY, [
                "[class*='cookie-overlay']",
                "[class*='consent-overlay']",
                "[class*='cookie-wall']",
                "[class*='consent-wall']",
            ]),
        ]
        for fmt, selectors in generic_map:
            for sel in selectors:
                el = await self._try_visible(page, sel)
                if el:
                    return el, fmt

        # 3. JS format detection — inspect computed styles to classify
        try:
            detected = await page.evaluate(FORMAT_DETECTION_JS)
            fmt = detected.get("format", FORMAT_UNKNOWN)
            sel = detected.get("selector", "")
            if sel and fmt != FORMAT_UNKNOWN:
                el = await self._try_visible(page, sel)
                if el:
                    return el, fmt
        except Exception:
            pass

        return None, FORMAT_UNKNOWN

    async def _extract_banner_facts(self, page: Page, banner) -> dict:
        """
        Extract structured element facts from the banner via JS.
        Sends ~200 tokens of structured data to Claude instead of
        2000-3000 tokens of raw HTML.
        """
        try:
            handle = await banner.element_handle()
            return await page.evaluate("""
                (el) => {
                    const vis   = e => e.offsetWidth > 0 && e.offsetHeight > 0;
                    const attrs = e => ({
                        tag:         e.tagName.toLowerCase(),
                        text:        (e.innerText || '').trim().slice(0, 120) || null,
                        role:        e.getAttribute('role'),
                        ariaLabel:   e.getAttribute('aria-label'),
                        ariaLabelled: !!e.getAttribute('aria-labelledby'),
                        ariaModal:   e.getAttribute('aria-modal'),
                        tabIndex:    e.getAttribute('tabindex'),
                        dataTestId:  e.getAttribute('data-testid'),
                        dataConsent: e.getAttribute('data-consent'),
                    });
                    return {
                        role:       el.getAttribute('role'),
                        ariaModal:  el.getAttribute('aria-modal'),
                        ariaLabel:  el.getAttribute('aria-label'),
                        headings:   Array.from(el.querySelectorAll('h1,h2,h3,h4'))
                                        .map(h => h.innerText.trim().slice(0, 150))
                                        .filter(Boolean),
                        buttons:    Array.from(el.querySelectorAll('button,[role="button"]'))
                                        .filter(vis).map(attrs),
                        links:      Array.from(el.querySelectorAll('a'))
                                        .filter(e => vis(e) && (e.innerText || '').trim())
                                        .map(attrs),
                        checkboxes: Array.from(el.querySelectorAll('input[type="checkbox"]'))
                                        .map(e => ({
                                            label:    (e.labels?.[0]?.innerText ||
                                                       e.getAttribute('aria-label') || '').trim(),
                                            checked:  e.checked,
                                            disabled: e.disabled,
                                        })),
                    };
                }
            """, handle)
        except Exception:
            return {}

    async def _try_visible(self, page: Page, selector: str):
        """Try a selector, return element if visible, None otherwise."""
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=2000):
                return el
        except Exception:
            pass
        return None

    async def _measure_contrast(self, page: Page,
                                reject_el, accept_el) -> dict:
        try:
            def hex_to_rgb(h):
                h = h.lstrip("#")
                return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

            def relative_luminance(rgb):
                def c(x):
                    x /= 255
                    return x/12.92 if x <= 0.03928 else ((x+0.055)/1.055)**2.4
                r, g, b = rgb
                return 0.2126*c(r) + 0.7152*c(g) + 0.0722*c(b)

            def contrast_ratio(l1, l2):
                lighter = max(l1, l2)
                darker = min(l1, l2)
                return (lighter + 0.05) / (darker + 0.05)

            rej_style = await page.evaluate(
                """(el) => {
                    const s = window.getComputedStyle(el);
                    return {color: s.color, bg: s.backgroundColor};
                }""", await reject_el.element_handle()
            )
            acc_style = await page.evaluate(
                """(el) => {
                    const s = window.getComputedStyle(el);
                    return {color: s.color, bg: s.backgroundColor};
                }""", await accept_el.element_handle()
            )

            def parse_rgb(css_color):
                nums = re.findall(r'\d+', css_color)
                if len(nums) >= 3:
                    return tuple(int(x) for x in nums[:3])
                return (128, 128, 128)

            rej_fg = parse_rgb(rej_style.get("color", "rgb(0,0,0)"))
            rej_bg = parse_rgb(rej_style.get("bg", "rgb(255,255,255)"))
            acc_fg = parse_rgb(acc_style.get("color", "rgb(0,0,0)"))
            acc_bg = parse_rgb(acc_style.get("bg", "rgb(255,255,255)"))

            rej_ratio = contrast_ratio(
                relative_luminance(rej_fg),
                relative_luminance(rej_bg)
            )
            acc_ratio = contrast_ratio(
                relative_luminance(acc_fg),
                relative_luminance(acc_bg)
            )

            return {
                "reject_ratio":   round(rej_ratio, 2),
                "accept_ratio":   round(acc_ratio, 2),
                "ratio_diff":     round(abs(acc_ratio - rej_ratio), 2),
                "wcag_aa_reject": rej_ratio >= 4.5,
                "wcag_aa_accept": acc_ratio >= 4.5,
                "reject_style":   rej_style,
                "accept_style":   acc_style,
            }
        except Exception as e:
            return {"error": str(e)}

    def _parse_consent_mode(self, pushes: list) -> dict:
        default_push = None
        update_pushes = []
        for batch in pushes:
            for item in batch:
                if isinstance(item, dict):
                    if item.get("0") == "consent" or \
                       (isinstance(item, dict) and
                            item.get("consent") and
                            item.get("default")):
                        default_push = item
                    if "update" in str(item).lower():
                        update_pushes.append(item)
        return {
            "detected": default_push is not None,
            "default_state": default_push,
            "update_pushes": update_pushes,
            "ad_storage_default_denied": (
                default_push is not None and
                str(default_push).find("denied") != -1
            ),
        }

    def _scan_fourth_parties(self, request_log: list) -> dict:
        known_third_parties = {
            "consent.cookiebot.com": "CMP",
            "google-analytics.com": "analytics",
            "googletagmanager.com": "tag_manager",
            "facebook.net": "advertising",
            "doubleclick.net": "advertising",
            "hotjar.com": "analytics",
        }
        domains_seen = {}
        for req in request_log:
            try:
                domain = urlparse(req["url"]).netloc
                initiator = urlparse(req.get("initiator", "")).netloc
                if domain not in domains_seen:
                    domains_seen[domain] = {
                        "category": known_third_parties.get(domain, "unknown"),
                        "loaded_by": initiator or "direct",
                        "is_fourth_party": (
                            initiator and
                            initiator != domain and
                            initiator in known_third_parties
                        ),
                        "request_count": 0,
                    }
                domains_seen[domain]["request_count"] += 1
            except Exception:
                continue

        # Baseline comparison
        new_domains = []
        baseline = self._load_baseline()
        if baseline:
            known = set(baseline.get("domains", {}).keys())
            new_domains = [d for d in domains_seen if d not in known]
        else:
            self._save_baseline({"domains": domains_seen})

        return {
            "domains": domains_seen,
            "new_since_baseline": new_domains,
            "fourth_parties": [
                d for d, v in domains_seen.items()
                if v.get("is_fourth_party")
            ],
        }

    async def _run_axe(self, page: Page) -> list:
        try:
            await page.add_script_tag(url=AXE_CDN)
            await page.wait_for_timeout(1000)
            violations = await page.evaluate("""
                async () => {
                    const result = await axe.run(
                        document.querySelector(
                            '#CybotCookiebotDialog, [id*=cookie], [role=dialog]'
                        ) || document.body,
                        { runOnly: ['wcag2a', 'wcag2aa', 'best-practice'] }
                    );
                    return result.violations.map(v => ({
                        id:          v.id,
                        impact:      v.impact,
                        description: v.description,
                        nodes:       v.nodes.length,
                    }));
                }
            """)
            return violations
        except Exception as e:
            return [{"error": str(e)}]

    def _compute_score(self, results: dict) -> float:
        score = 1.0
        weights = {
            "pre_consent_cookies": 0.40,
            "reject_button":       0.30,
            "consent_mode_v2":     0.20,
            "axe_critical":        0.10,
        }
        penalties = []

        if results.get("pre_consent_cookies"):
            penalties.append(("pre_consent_cookies",
                              weights["pre_consent_cookies"]))

        if not results.get("reject_button_found"):
            penalties.append(("reject_button_missing",
                              weights["reject_button"]))

        cmv2 = results.get("consent_mode_v2", {})
        if cmv2.get("detected") and not cmv2.get("ad_storage_default_denied"):
            penalties.append(("consent_mode_v2_incorrect",
                              weights["consent_mode_v2"]))

        critical_axe = [
            v for v in results.get("axe_violations", [])
            if v.get("impact") == "critical"
        ]
        if critical_axe:
            penalties.append(("axe_critical_violations",
                              weights["axe_critical"] * len(critical_axe)))

        for _, penalty in penalties:
            score -= penalty

        results["penalty_breakdown"] = penalties
        return max(0.0, round(score, 3))

    def _domain(self) -> str:
        return urlparse(self.url).netloc

    def _load_baseline(self) -> Optional[dict]:
        try:
            with open(self.baseline_path) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_baseline(self, data: dict):
        os.makedirs(os.path.dirname(self.baseline_path), exist_ok=True)
        with open(self.baseline_path, "w") as f:
            json.dump(data, f, indent=2)
