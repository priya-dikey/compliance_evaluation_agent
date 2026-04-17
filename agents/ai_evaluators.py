"""
agents/ai_evaluators.py
Claude-powered compliance reasoning agents.
Temperature=0, structured JSON output, evidence-anchored prompts.
Facts come from Playwright — Claude reasons about their meaning.
"""

import json
import re
import anthropic


MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1000

# ── Static prompt sections — module-level so they're built once ───────────────

_A11Y_FORMATS = """
BANNER: role="region" or "complementary" with aria-label; focus NOT trapped; Tab freely; Escape must NOT dismiss without a consent choice.
MODAL: MUST have role="dialog" and aria-modal="true"; MUST have aria-labelledby; focus MUST be trapped; Escape behaviour must be audited.
OVERLAY: MUST have role="dialog" or "alertdialog"; focus fully trapped; all elements reachable via Tab without scrolling; touch targets >= 44×44px on mobile."""

_UX_FORMATS = """
BANNER: re-appearing after dismissal (nagging)? dismissible via X without a consent choice (implied consent)?
MODAL: dismiss via backdrop/X without choosing? reject buried in a secondary tab? focus trap prevents reaching reject via Tab?
OVERLAY: blocks all page content until choice (forced action)? reject requires scrolling off-screen? visual design disproportionately coerces acceptance?"""


class AIEvaluators:
    def __init__(self, compliance_rules: dict):
        self.rules = compliance_rules
        self.client = anthropic.AsyncAnthropic()
        self._rules_json = json.dumps(compliance_rules, indent=2)

    async def evaluate_compliance(self, context: dict) -> dict:
        cmp_name      = context.get("cmp_name", "Unknown CMP")
        banner_format = context.get("banner_format", "unknown")
        evidence = {
            "pre_consent_cookies_detected": bool(context.get("pre_consent_cookies")),
            "pre_consent_cookie_names":     list(context.get("pre_consent_cookies", {}).keys()),
            "reject_button_found":          context.get("reject_button_found", False),
            "accept_button_found":          context.get("accept_button_found", False),
            "banner_format":                banner_format,
            "contrast_ratio_reject":        context.get("contrast_ratios", {}).get("reject_ratio"),
            "contrast_ratio_accept":        context.get("contrast_ratios", {}).get("accept_ratio"),
            "contrast_ratio_diff":          context.get("contrast_ratios", {}).get("ratio_diff"),
            "consent_mode_v2_detected":     context.get("consent_mode_v2", {}).get("detected"),
            "fourth_parties":               context.get("fourth_parties", {}).get("fourth_parties", []),
        }

        static_text = f"""You are a GDPR compliance expert conducting a cookie consent audit.

COMPLIANCE RULES IN EFFECT:
{self._rules_json}

Do not guess — base findings strictly on the measurements and HTML provided.
An overlay blocking all content until acceptance may constitute forced consent (GDPR Art.7).

Return ONLY this JSON (no preamble, no markdown):
{{
  "score": 1-5,
  "violations": [
    {{"rule": "gdpr_article_or_principle", "severity": "critical|high|medium|low",
      "finding": "one factual sentence grounded in evidence",
      "evidence": "exact measurement or HTML element", "confidence": 0.0-1.0}}
  ],
  "dark_patterns_detected": [],
  "compliant": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence summary"
}}"""

        variable_text = f"""CMP: {cmp_name}  BANNER FORMAT: {banner_format.upper()}

DETERMINISTIC MEASUREMENTS (from Playwright — treat as facts):
{json.dumps(evidence, indent=2)}

BANNER ELEMENTS (extracted by Playwright):
{json.dumps(context.get("banner_facts", {}), indent=2)}"""

        content = self._build_content(
            static_text, variable_text, context.get("screenshot_b64", ""))
        return await self._call(content, "compliance")

    async def evaluate_accessibility(self, context: dict) -> dict:
        banner_format = context.get("banner_format", "unknown")
        device        = context.get("device", "Desktop Chrome")
        is_mobile     = "iphone" in device.lower() or "pixel" in device.lower()

        static_text = f"""You are a WCAG 2.1 AA accessibility expert auditing a cookie consent UI.

STANDARD CHECKS (all formats):
- Colour contrast >= 4.5:1 (normal text), >= 3:1 (large text)
- All interactive elements keyboard-reachable and operable via Tab/Enter/Space
- Buttons have accessible names (not icon-only)
- Language attribute present for non-English content

FORMAT-SPECIFIC REQUIREMENTS:
{_A11Y_FORMATS}

MOBILE (when applicable): touch targets >= 44×44px (WCAG 2.5.5); readable without zoom; buttons not obscured by virtual keyboard.

Base findings strictly on axe results and contrast measurements. Do not speculate.

Return ONLY this JSON:
{{
  "score": 1-5,
  "banner_format": "{banner_format}",
  "violations": [
    {{"rule": "wcag_criterion", "severity": "critical|high|medium|low",
      "finding": "factual sentence referencing measurement or axe result",
      "evidence": "axe violation id, contrast ratio, or HTML attribute", "confidence": 0.0-1.0}}
  ],
  "keyboard_navigable": true/false,
  "focus_trap_correct": true/false,
  "screen_reader_compatible": true/false,
  "aria_role_correct": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence summary"
}}"""

        variable_text = f"""BANNER FORMAT: {banner_format.upper()}  DEVICE: {device}{"  (MOBILE)" if is_mobile else ""}

AXE-CORE VIOLATIONS (deterministic — treat as facts):
{json.dumps(context.get("axe_violations", []), indent=2)}

CONTRAST RATIOS (WCAG AA min 4.5:1 normal / 3:1 large):
{json.dumps(context.get("contrast_ratios", {}), indent=2)}

BANNER ELEMENTS (extracted by Playwright):
{json.dumps(context.get("banner_facts", {}), indent=2)}"""

        content = self._build_content(
            static_text, variable_text, context.get("screenshot_b64", ""))
        return await self._call(content, "accessibility")

    async def evaluate_ux(self, context: dict) -> dict:
        banner_format   = context.get("banner_format", "unknown")
        contrast_ratios = context.get("contrast_ratios", {})

        static_text = f"""You are a UX compliance expert specialising in consent dark patterns.
Reference: EDPB Guidelines on Dark Patterns (March 2022).

ALL-FORMAT CHECKS:
1. Misleading information (false urgency, deceptive framing, confusing language)
2. Unequal visual weight (accept prominent, reject visually deprioritised)
3. Interface interference (confusing layout, misleading button labels)
4. Hidden options (reject buried in settings or requiring more clicks than accept)
5. Pre-selected options (optional categories ticked by default)

FORMAT-SPECIFIC CHECKS:
{_UX_FORMATS}

Return ONLY this JSON:
{{
  "score": 1-5,
  "banner_format": "{banner_format}",
  "violations": [
    {{"rule": "edpb_dark_pattern_category", "severity": "critical|high|medium|low",
      "finding": "factual description of the pattern observed",
      "evidence": "contrast ratio, HTML element, or observed behaviour", "confidence": 0.0-1.0}}
  ],
  "accept_reject_prominence_equal": true/false,
  "dismissible_without_choice": true/false,
  "reject_requires_extra_clicks": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence summary"
}}"""

        variable_text = f"""CMP: {context.get("cmp_name", "Unknown")}  BANNER FORMAT: {banner_format.upper()}

CONTRAST (accept={contrast_ratios.get("accept_ratio", "?")}, reject={contrast_ratios.get("reject_ratio", "?")}, diff={contrast_ratios.get("ratio_diff", "?")} — diff > 2.0 indicates unequal visual weight)

BANNER ELEMENTS (extracted by Playwright):
{json.dumps(context.get("banner_facts", {}), indent=2)}"""

        content = self._build_content(
            static_text, variable_text, context.get("screenshot_b64", ""))
        return await self._call(content, "ux")

    def _build_content(
        self, static_text: str, variable_text: str, screenshot_b64: str | None
    ) -> list:
        """Image cached first (saves screenshot tokens on re-runs), then static
        instructions (second cache breakpoint), then variable evidence."""
        content: list = []
        if screenshot_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
                "cache_control": {"type": "ephemeral"},
            })
        content.append({
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        })
        content.append({"type": "text", "text": variable_text})
        return content

    async def _call(self, content: list, evaluator_name: str, model: str = MODEL) -> dict:
        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )
            text = re.sub(r"```json|```", "", response.content[0].text.strip()).strip()
            result = json.loads(text)
            u = response.usage
            cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
            cache_read  = getattr(u, "cache_read_input_tokens", 0) or 0
            result["tokens_used"] = u.input_tokens + u.output_tokens
            result["evaluator"] = evaluator_name
            parts = [f"in={u.input_tokens}", f"out={u.output_tokens}"]
            if cache_write:
                parts.append(f"cache_write={cache_write}")
            if cache_read:
                parts.append(f"cache_read={cache_read}")
            print(f"  [tokens] {evaluator_name}: {' '.join(parts)}")
            return result
        except json.JSONDecodeError as e:
            return {"score": 0, "violations": [], "confidence": 0.0,
                    "error": f"JSON parse error: {e}", "evaluator": evaluator_name,
                    "tokens_used": 0}
        except Exception as e:
            return {"score": 0, "violations": [], "confidence": 0.0,
                    "error": str(e), "evaluator": evaluator_name, "tokens_used": 0}
