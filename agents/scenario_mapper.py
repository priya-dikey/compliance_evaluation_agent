"""
agents/scenario_mapper.py
Maps orchestrator output to the 17 BDD scenarios in features/cookie_consent.feature.
No Behave/step-definition framework needed — uses data already collected by
DeterministicAgent and AIEvaluators.

Each result:
  {id, title, group, status: PASS|FAIL|PARTIAL|SKIP, evidence, details}
"""

PASS    = "PASS"
FAIL    = "FAIL"
PARTIAL = "PARTIAL"
SKIP    = "SKIP"

# Canonical scenario definitions (mirrors features/cookie_consent.feature order)
SCENARIO_DEFS = [
    (1,  "Banner appears on first visit",                   "Banner Presence"),
    (2,  "Banner does not reappear after consent given",    "Banner Presence"),
    (3,  "Banner reappears after consent expiry",           "Banner Presence"),
    (4,  "No tracking before consent — fresh visitor",      "Pre-consent Tracking"),
    (5,  "No tracking after rejection",                     "Pre-consent Tracking"),
    (6,  "Accept all enables all cookie categories",        "Accept Behaviour"),
    (7,  "Reject option is present and equally prominent",  "Reject Behaviour"),
    (8,  "Reject all prevents all non-essential processing","Reject Behaviour"),
    (9,  "Granular consent categories are available",       "Granular Consent"),
    (10, "Pre-ticked boxes are forbidden",                  "Granular Consent"),
    (11, "Consent can be withdrawn after acceptance",       "Consent Withdrawal"),
    (12, "Cookie banner is keyboard navigable",             "Accessibility"),
    (13, "Screen reader announces banner correctly",        "Accessibility"),
    (14, "Consent Mode v2 defaults to denied",              "Consent Mode v2"),
    (15, "Consent Mode v2 updates on accept",               "Consent Mode v2"),
]


def _r(id_, status, evidence, details=""):
    sid, title, group = next(s for s in SCENARIO_DEFS if s[0] == id_)
    return {
        "id":       sid,
        "title":    title,
        "group":    group,
        "status":   status,
        "evidence": evidence,
        "details":  details,
    }


class ScenarioMapper:
    """Call .map(report_dict) after a full orchestrator run."""

    def map(self, report: dict) -> list:
        det = report.get("deterministic", {})
        ai  = report.get("ai_evaluations", {})
        ic  = det.get("interaction_checks", {})
        cc  = det.get("context_checks", {})

        return [
            self._s1(det),
            self._s2(cc),
            self._s3(cc),
            self._s4(det),
            self._s5(ic),
            self._s6(ic),
            self._s7(det),
            self._s8(ic),
            self._s9(ic),
            self._s10(det, ic),
            self._s11(ic),
            self._s12(det, ai),
            self._s13(det, ai),
            self._s14(det),
            self._s15(ic),
        ]

    # ── Banner Presence ───────────────────────────────────────────────────────

    def _s1(self, det):
        found = det.get("primary_context", {}).get("banner_found", False)
        fmt   = det.get("banner_format", "unknown")
        return _r(1,
            PASS if found else FAIL,
            f"Banner {'found' if found else 'not found'} (format: {fmt})",
        )

    def _s2(self, cc):
        ctx = cc.get("returning_accepted", {})
        if not ctx or "error" in ctx:
            return _r(2, SKIP, "returning_accepted context not run")
        found = ctx.get("banner_found", True)
        return _r(2,
            FAIL if found else PASS,
            f"Banner {'still shown' if found else 'correctly hidden'} with prior-accepted consent cookie",
        )

    def _s3(self, cc):
        ctx = cc.get("expired_consent", {})
        if not ctx or "error" in ctx:
            return _r(3, SKIP, "expired_consent context not run")
        found = ctx.get("banner_found", False)
        return _r(3,
            PASS if found else FAIL,
            f"Banner {'correctly re-shown' if found else 'not shown'} with expired consent cookie",
        )

    # ── Pre-consent Tracking ──────────────────────────────────────────────────

    def _s4(self, det):
        pre = det.get("pre_consent_cookies", {})
        if not pre:
            return _r(4, PASS, "No non-essential cookies detected before consent interaction")
        names = list(pre.keys())[:5]
        return _r(4, FAIL, f"{len(pre)} tracking cookie(s) set before consent: {', '.join(names)}")

    def _s5(self, ic):
        r = ic.get("post_reject", {})
        if not r or "error" in r:
            return _r(5, SKIP, r.get("error", "Post-reject check not run") if r else "Post-reject check not run")
        if not r.get("reject_found"):
            return _r(5, FAIL, "Reject button not found — could not test post-rejection tracking")
        if not r.get("banner_dismissed"):
            return _r(5, PARTIAL, "Reject clicked but banner did not dismiss")
        cookies = r.get("post_reject_cookies", {})
        return _r(5,
            FAIL if cookies else PASS,
            (f"{len(cookies)} tracking cookie(s) still set after rejection: {list(cookies.keys())[:3]}"
             if cookies else "No tracking cookies set after rejection"),
        )

    # ── Accept Behaviour ──────────────────────────────────────────────────────

    def _s6(self, ic):
        r = ic.get("post_accept", {})
        if not r or "error" in r:
            return _r(6, SKIP, r.get("error", "Post-accept check not run") if r else "Post-accept check not run")
        if not r.get("accept_found"):
            return _r(6, FAIL, "Accept button not found — could not test post-acceptance cookies")
        cookies  = r.get("post_accept_cookies", {})
        cmv2_ok  = r.get("cmv2_analytics_granted", False)
        if cookies or cmv2_ok:
            return _r(6, PASS,
                f"Analytics cookies set: {bool(cookies)}, "
                f"CMv2 analytics_storage=granted: {cmv2_ok}",
            )
        return _r(6, FAIL, "No analytics cookies or CMv2 grant detected after accept")

    # ── Reject Behaviour ──────────────────────────────────────────────────────

    def _s7(self, det):
        reject   = det.get("reject_button_found", False)
        contrast = det.get("contrast_ratios", {})
        ratio    = contrast.get("reject_ratio", 0)
        wcag     = contrast.get("wcag_aa_reject", False)
        if not reject:
            return _r(7, FAIL, "Reject button not found on banner")
        if not wcag and ratio:
            return _r(7, PARTIAL,
                f"Reject button found but contrast {ratio:.2f}:1 fails WCAG AA (need 4.5:1)")
        return _r(7, PASS,
            f"Reject button found{', contrast ' + str(ratio) + ':1 passes WCAG AA' if ratio else ''}")

    def _s8(self, ic):
        r = ic.get("post_reject", {})
        if not r or "error" in r:
            return _r(8, SKIP, r.get("error", "Post-reject check not run") if r else "Post-reject check not run")
        if not r.get("reject_found"):
            return _r(8, FAIL, "Reject button not found")
        cookies     = r.get("post_reject_cookies", {})
        cmv2_denied = r.get("cmv2_ad_denied", False)
        if not cookies and cmv2_denied:
            return _r(8, PASS, "No tracking cookies set and CMv2 ad_storage=denied after rejection")
        if not cookies:
            return _r(8, PARTIAL,
                "No tracking cookies after rejection, but CMv2 ad_storage state not confirmed")
        return _r(8, FAIL, f"{len(cookies)} non-essential cookie(s) set after rejection: {list(cookies.keys())[:3]}")

    # ── Granular Consent ──────────────────────────────────────────────────────

    def _s9(self, ic):
        r = ic.get("granular_prefs", {})
        if not r or "error" in r:
            return _r(9, SKIP, r.get("error", "Preferences panel check not run") if r else "Preferences panel check not run")
        if not r.get("panel_opened"):
            return _r(9, FAIL, "Preferences button not found or panel did not open")
        cats  = r.get("categories", [])
        lower = " ".join(cats).lower()
        missing = [c for c in ("necessary", "analytics", "marketing") if c not in lower]
        if missing:
            return _r(9, PARTIAL,
                f"Panel opened, categories found: {cats}. Missing expected: {missing}")
        return _r(9, PASS, f"Preferences panel opened with categories: {cats}")

    def _s10(self, det, ic):
        # Check main banner checkboxes first
        facts = det.get("primary_context", {}).get("banner_facts", {})
        optional_ticked = [
            b["label"] for b in facts.get("checkboxes", [])
            if b.get("checked") and not b.get("disabled")
               and "necessary" not in b.get("label", "").lower()
        ]
        if optional_ticked:
            return _r(10, FAIL, f"Optional categories pre-ticked on banner: {optional_ticked}")
        # Also check preferences panel
        r = ic.get("granular_prefs", {})
        if r and r.get("panel_opened"):
            prefs_ticked = r.get("optional_prechecked", [])
            if prefs_ticked:
                return _r(10, FAIL, f"Optional categories pre-ticked in preferences panel: {prefs_ticked}")
            return _r(10, PASS, "No optional categories pre-ticked in banner or preferences panel")
        if not facts.get("checkboxes"):
            return _r(10, PARTIAL,
                "No checkboxes found on banner; preferences panel not opened to verify")
        return _r(10, PASS, "No optional categories pre-ticked on banner")

    # ── Consent Withdrawal ────────────────────────────────────────────────────

    def _s11(self, ic):
        r = ic.get("withdrawal", {})
        if not r or "error" in r:
            return _r(11, SKIP, r.get("error", "Withdrawal check not run") if r else "Withdrawal check not run")
        link  = r.get("preferences_link_found", False)
        panel = r.get("panel_opened", False)
        if not link:
            return _r(11, FAIL, "No cookie preferences link found after acceptance")
        if not panel:
            return _r(11, PARTIAL, "Preferences link found but panel did not open")
        return _r(11, PASS, "Preferences link accessible and panel opens after prior acceptance")

    # ── Accessibility ─────────────────────────────────────────────────────────

    def _s12(self, det, ai):
        axe     = det.get("axe_violations", [])
        kb_axe  = [v for v in axe if "keyboard" in v.get("id", "") or "focus" in v.get("id", "")]
        a11y_ai = ai.get("accessibility", {})
        kb_ok   = a11y_ai.get("keyboard_navigable")
        if kb_axe:
            return _r(12,
                FAIL if kb_ok is False else PARTIAL,
                f"{len(kb_axe)} keyboard/focus axe violation(s): {[v.get('id') for v in kb_axe[:3]]}",
            )
        if kb_ok is False:
            return _r(12, FAIL, "AI accessibility evaluator: keyboard navigation not functional")
        return _r(12, PASS,
            f"No keyboard axe violations; AI evaluator keyboard_navigable={kb_ok}")

    def _s13(self, det, ai):
        facts      = det.get("primary_context", {}).get("banner_facts", {})
        role       = facts.get("role")
        aria_modal = facts.get("ariaModal")
        a11y_ai    = ai.get("accessibility", {})
        sr_ok      = a11y_ai.get("screen_reader_compatible")
        role_ok    = a11y_ai.get("aria_role_correct")
        if not role and not aria_modal:
            status = FAIL if sr_ok is False else PARTIAL
            return _r(13, status,
                f"Banner missing role/aria-modal; AI sr_compatible={sr_ok}")
        if sr_ok and role_ok:
            return _r(13, PASS,
                f"role={role}, aria-modal={aria_modal}, AI sr_compatible=True")
        return _r(13, PARTIAL,
            f"role={role}, aria-modal={aria_modal}, AI sr_compatible={sr_ok}")

    # ── Consent Mode v2 ───────────────────────────────────────────────────────

    def _s14(self, det):
        cmv2 = det.get("consent_mode_v2", {})
        if not cmv2.get("detected"):
            return _r(14, SKIP, "Google Tag Manager / Consent Mode v2 not detected on page")
        if cmv2.get("ad_storage_default_denied"):
            return _r(14, PASS, "CMv2 detected with ad_storage defaulted to denied")
        return _r(14, FAIL, "CMv2 detected but ad_storage not defaulted to denied")

    def _s15(self, ic):
        r = ic.get("post_accept", {})
        if not r or "error" in r:
            return _r(15, SKIP, r.get("error", "Post-accept check not run") if r else "Post-accept check not run")
        analytics = r.get("cmv2_analytics_granted", False)
        ad_denied = r.get("cmv2_ad_still_denied", False)
        if analytics and ad_denied:
            return _r(15, PASS,
                "CMv2 update push: analytics_storage=granted, ad_storage=denied")
        if analytics:
            return _r(15, PARTIAL,
                "CMv2 analytics_storage=granted but ad_storage state not confirmed")
        return _r(15, FAIL,
            "No CMv2 analytics_storage=granted update detected after accept")
