# Hybrid QA Agent — Cookie Consent Compliance

AI-powered QA agent that combines deterministic Playwright testing with
Claude-based compliance reasoning to audit cookie consent banners against
GDPR Art.5/7, WCAG 2.1 AA, and EDPB dark pattern guidelines.

---

## Architecture

```
Orchestrator
├── Step 0  Compliance Rules      secureprivacy.ai → GDPR fallback chain
├── Step 1  Deterministic Layer   Playwright: facts, measurements, timing
│           ├── Primary run       fresh visitor · primary browser · EU locale
│           ├── Context checks    returning_accepted · expired_consent (parallel)
│           ├── Interaction tests post-reject · post-accept · granular prefs · withdrawal (parallel)
│           └── Cross-browser     Firefox · Safari · iPhone · Pixel (parallel)
├── Step 2  AI Reasoning Layer    Claude: compliance · accessibility · UX (parallel)
├── Step 3  Multi-Evaluator Vote  weighted aggregation with compliance veto
├── Step 4  Final Evaluation      score · risk · pipeline action
├── Step 5  Scenario Mapper       15 BDD scenarios → PASS/FAIL/PARTIAL/SKIP
└──         Report Generator      JSON + self-contained HTML
```

**Key design principle:** Playwright extracts facts. Claude reasons about their
compliance meaning. Never fabricate — if a measurement fails, fail explicitly.

---

## Setup

```bash
pip install -r requirements.txt
playwright install --with-deps chromium firefox webkit
export ANTHROPIC_API_KEY=your_key_here
```

## Run

```bash
# Full run (all browsers, all contexts, all scenarios)
python orchestrator.py --url https://en.giesswein.com/

# Fast run (primary browser + fresh context only — skips context/interaction checks)
python orchestrator.py --url https://en.giesswein.com/ --fast

# Custom output path
python orchestrator.py --url https://en.giesswein.com/ --output reports/my-report.json
```

Outputs `reports/report.json` and `reports/report.html`.

## Exit codes (CI/CD)

- `0` — PASS or WARN (pipeline continues)
- `1` — BLOCK (critical violation + confidence ≥ 0.85 + deterministic evidence)

---

## What each layer tests

| Layer | Tool | Tests | Blocks pipeline? |
|---|---|---|---|
| Deterministic | Playwright | Pre-consent cookies, CMv2 defaults, 4th parties, axe-core | Always |
| Context checks | Playwright | Banner suppressed for returning users; re-shown after expiry | Via score |
| Interaction tests | Playwright | Post-reject/accept cookies; granular panel; consent withdrawal | Via score |
| Self-healing | Claude Haiku | Classifies selector failures, heals SELECTOR_DRIFT only | Never masks real failures |
| Compliance | Claude Sonnet | GDPR Art.5/7, dark patterns, consent validity | If critical + confident |
| Accessibility | Claude Sonnet + axe | WCAG 2.1 AA, keyboard nav, focus trap, screen reader | If critical + confident |
| UX | Claude Sonnet | EDPB dark pattern categories, visual weight | If critical + confident |
| Scenario mapper | — | Maps all 15 BDD scenarios to PASS/FAIL/PARTIAL/SKIP | Reporting only |

## Pipeline action logic

BLOCK requires ALL THREE:
1. Critical severity violation with confidence ≥ 0.85
2. Deterministic evidence corroborating the finding
3. Compliance veto triggered

This prevents false positives from blocking legitimate deployments.

---

## Feature coverage

All 15 scenarios in `features/cookie_consent.feature` are evaluated on every
full run without a separate BDD test runner. Results appear in the HTML report
under **Feature Coverage**.

| # | Group | Data source |
|---|---|---|
| 1 – 3 | Banner Presence | Primary run + context checks |
| 4 – 5 | Pre-consent Tracking | Pre-consent cookie scan + post-reject check |
| 6 | Accept Behaviour | Post-accept cookies + CMv2 update push |
| 7 – 8 | Reject Behaviour | Reject button found + contrast ratios + post-reject cookies |
| 9 – 10 | Granular Consent | Preferences panel opened + checkbox states |
| 11 | Consent Withdrawal | Preferences link reachable after prior acceptance |
| 12 – 13 | Accessibility | axe-core violations + AI accessibility evaluator |
| 14 – 15 | Consent Mode v2 | CMv2 default state + post-accept update push |

> **Note:** Scenarios 2, 3 are SKIP in `--fast` mode (only one context is run).
> Scenarios 14, 15 are SKIP when Google Tag Manager is not present on the page.

---

## Eval tests

Agent capability tests live in `tests/evals/`. They verify each Claude agent
produces correct structured output on known-good and known-bad fixtures —
without running a full browser session.

```bash
pytest tests/evals/ -v                        # all evals (uses API credits)
pytest tests/evals/ -v -k "schema"           # schema only — zero API cost
pytest tests/evals/test_selfheal_eval.py -v  # self-heal safety gate only
```

| Test file | What it guards |
|---|---|
| `test_compliance_eval.py` | Schema correctness · detects pre-consent cookies · detects missing reject · no false positives on clean banner |
| `test_selfheal_eval.py` | Schema correctness · SELECTOR_DRIFT detected · **FUNCTIONAL_REMOVAL never healed** · confidence calibration |

The most critical test is `test_functional_removal_no_selector` — it ensures the
self-healing agent never masks a real regression as a selector change.

---

## Cost optimisation

| Technique | Saving |
|---|---|
| Prompt caching (`cache_control: ephemeral`) | ~70% token reduction on repeat evaluator calls |
| `AsyncAnthropic` + `asyncio.gather` | 3 evaluators run in parallel (compliance + a11y + ux) |
| Claude Haiku for self-healing classification | ~10× cheaper than Sonnet for simple tasks |
| Structured `banner_facts` instead of raw HTML | ~200 tokens vs ~3,000 tokens per call |
| Screenshot only for compliance/a11y/ux — not geo | Saves image tokens on non-visual checks |

Typical cost per full run: **~$0.02–0.04** depending on site complexity.

---

## Files

```
orchestrator.py                  Main entry point (5 steps)
evaluation.py                    Scoring + pipeline decision
pytest.ini                       pytest asyncio_mode = auto
config/
  compliance_rules.py            Rule fetcher with fallback chain
  cmp_registry.py                CMP profiles + selector strategies per site
agents/
  deterministic.py               Playwright test layer (facts + interaction tests)
  self_healing.py                4-level selector fallback with AI recovery
  ai_evaluators.py               Claude evaluation agents (compliance / a11y / ux)
  voting.py                      Multi-evaluator weighted aggregation
  scenario_mapper.py             Maps orchestrator output → 15 BDD scenario results
features/
  cookie_consent.feature         Gherkin BDD specification (15 GDPR scenarios)
reports/
  generate_report.py             Self-contained HTML report generator
  example_output.json            Realistic example output
tests/
  evals/
    fixtures.py                  Golden-dataset fixtures (FAILING_BANNER, PASSING_BANNER, HTML_*)
    test_compliance_eval.py      12 eval tests — compliance + accessibility + ux agents
    test_selfheal_eval.py        7 eval tests — self-healing safety gate
```

## Self-healing levels

```
PRIMARY      → CMP-specific selector (from cmp_registry.py)
SECONDARY    → Alternative CMP selector
HEURISTIC_1  → Regex text match (accept all|allow all|agree…)
HEURISTIC_2  → Broader fallback
AI_RECOVERY  → Claude Haiku classifies failure type:
               SELECTOR_DRIFT     → heal (update per-site cache)
               LAYOUT_CHANGE      → heal + flag for human review
               FUNCTIONAL_REMOVAL → FAIL — never heal real regressions
               FUNCTIONAL_CHANGE  → FAIL — never heal real regressions
```

Healed selectors are cached per site (`reports/healing_cache.json`) with
composite key `"{host}::{element_key}"` to prevent cross-site leakage.
