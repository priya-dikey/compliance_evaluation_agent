"""
agents/self_healing.py
Self-healing selector wrapper with compliance safety gate.
Classifies failures before healing — never masks a real regression.
"""

import asyncio
import json
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse
import anthropic


from config.cmp_registry import build_selector_strategies, CMP_PROFILES, CMPProfile

# Built at runtime via set_cmp_profile() — falls back to heuristics only
_DEFAULT_STRATEGIES = {
    "accept_button":      ["button:has-text(/accept all|allow all|agree|enable cookies|accept cookies/i)", None],
    "reject_button":      ["button:has-text(/decline|deny|reject all|reject|refuse|only necessary|only essential|use essential cookies/i)", None],
    "preferences_button": ["button:has-text(/preferences|settings|customise|manage/i)", None],
}


LEVEL_NAMES = ["PRIMARY", "SECONDARY", "HEURISTIC_1",
               "HEURISTIC_2", "AI_RECOVERY"]


class SelfHealingAgent:
    def __init__(self):
        self.log: list = []
        self.healing_cache: dict = {}
        self._client = None
        self._strategies = dict(_DEFAULT_STRATEGIES)
        self._load_cache()

    def set_cmp_profile(self, profile: CMPProfile):
        """Call this after detecting the CMP so selectors are CMP-specific."""
        self._strategies = build_selector_strategies(profile)
        print(f"  [self-healing] Loaded selectors for: {profile.name}")

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def _cache_key(self, page_url: str, element_key: str) -> str:
        return f"{urlparse(page_url).netloc}::{element_key}"

    async def find_element(
        self, page, element_key: str, intent: str
    ):
        """
        Try selector hierarchy for element_key.
        Returns element or None. Logs every level attempted.
        """
        strategies = self._strategies.get(element_key, [None])

        # Check cache first (keyed per site)
        cache_key = self._cache_key(page.url, element_key)
        if cache_key in self.healing_cache:
            cached_sel = self.healing_cache[cache_key]
            el = await self._try_selector(page, cached_sel)
            if el:
                self._log_event(element_key, "CACHE_HIT", cached_sel, True)
                return el
            else:
                # Cache is stale — continue through hierarchy
                del self.healing_cache[cache_key]

        for i, selector in enumerate(strategies):
            level = LEVEL_NAMES[min(i, len(LEVEL_NAMES)-1)]

            if selector is None:
                # Claude recovery
                return await self._claude_recovery(
                    page, element_key, intent, level)

            el = await self._try_selector(page, selector)
            if el:
                self._log_event(element_key, level, selector, True)
                return el
            else:
                self._log_event(element_key, level, selector, False)

        return None

    async def _try_selector(self, page, selector: str):
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=2000):
                return el
        except Exception:
            pass
        return None

    async def _claude_recovery(
        self, page, element_key: str, intent: str, level: str
    ):
        """
        CRITICAL: Classify the failure before attempting to heal.
        Only heal SELECTOR_DRIFT. Fail on FUNCTIONAL_REMOVAL/CHANGE.
        """
        try:
            html = await page.content()
            html_snippet = html[:8000]  # truncate for context window

            classification = await self._classify_failure(
                element_key, intent, html_snippet)

            change_type = classification.get("change_type", "FUNCTIONAL_REMOVAL")
            confidence = classification.get("confidence", 0.0)

            self._log_event(
                element_key, f"AI_CLASSIFY_{change_type}",
                f"confidence={confidence:.2f}", False,
                extra=classification
            )

            # Safety gate — never heal functional failures
            if change_type in ("FUNCTIONAL_REMOVAL", "FUNCTIONAL_CHANGE"):
                print(f"  [self-healing] FAIL: {change_type} for "
                      f"{element_key} — not healing")
                return None

            if confidence < 0.85:
                print(f"  [self-healing] WARN: low confidence "
                      f"({confidence:.2f}) for {element_key} — "
                      f"not healing, flagging for human review")
                self._log_event(
                    element_key, "AI_LOW_CONFIDENCE",
                    f"confidence={confidence:.2f}", False,
                    extra={"human_review_required": True}
                )
                return None

            # Compliance-affecting layout changes — heal but flag
            if change_type == "LAYOUT_CHANGE":
                classification["compliance_impact"] = True
                self._log_event(
                    element_key, "AI_COMPLIANCE_FLAG",
                    "layout change may affect compliance", False,
                    extra={"human_review_required": True}
                )

            # Attempt healing
            new_selector = classification.get("new_selector")
            if not new_selector:
                return None

            el = await self._try_selector(page, new_selector)
            if el:
                # Cache the healed selector (scoped per site)
                cache_key = self._cache_key(page.url, element_key)
                self.healing_cache[cache_key] = new_selector
                self._save_cache()
                self._log_event(
                    element_key, "AI_HEALED", new_selector, True,
                    extra={
                        "reasoning": classification.get("reasoning"),
                        "compliance_impact":
                            classification.get("compliance_impact", False),
                        "auto_approved": not classification.get(
                            "compliance_impact", False),
                    }
                )
                return el

        except Exception as e:
            print(f"  [self-healing] Claude recovery error: {e}")
            self._log_event(element_key, "AI_ERROR", str(e), False)

        return None

    async def _classify_failure(
        self, element_key: str, intent: str, html: str
    ) -> dict:
        response = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0,
            messages=[{
                "role": "user",
                "content": f"""A Playwright test cannot find: "{intent}"
Element key: {element_key}

Current page HTML (truncated):
{html}

Classify this failure as exactly one of:
- SELECTOR_DRIFT: same functional element exists, selector changed
- LAYOUT_CHANGE: element exists but position/prominence changed
- FUNCTIONAL_REMOVAL: element/functionality no longer exists
- FUNCTIONAL_CHANGE: feature works differently now

If SELECTOR_DRIFT or LAYOUT_CHANGE, provide the new selector.

Return ONLY valid JSON:
{{
  "change_type": "SELECTOR_DRIFT|LAYOUT_CHANGE|FUNCTIONAL_REMOVAL|FUNCTIONAL_CHANGE",
  "confidence": 0.0-1.0,
  "new_selector": "css selector or null",
  "reasoning": "one sentence explanation",
  "compliance_impact": true/false
}}"""
            }]
        )
        u = response.usage
        print(f"  [tokens] self-healing/{element_key}: in={u.input_tokens} out={u.output_tokens}")
        text = re.sub(r"```json|```", "", response.content[0].text.strip()).strip()
        return json.loads(text)

    def _log_event(
        self, element_key: str, level: str,
        selector: str, success: bool, extra: dict = None
    ):
        event = {
            "timestamp": time.time(),
            "element":   element_key,
            "level":     level,
            "selector":  selector,
            "success":   success,
        }
        if extra:
            event.update(extra)
        self.log.append(event)

    def get_log(self) -> list:
        return self.log

    def _load_cache(self):
        try:
            with open("reports/healing_cache.json") as f:
                self.healing_cache = json.load(f)
        except Exception:
            self.healing_cache = {}

    def _save_cache(self):
        os.makedirs("reports", exist_ok=True)
        with open("reports/healing_cache.json", "w") as f:
            json.dump(self.healing_cache, f, indent=2)
