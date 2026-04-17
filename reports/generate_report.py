"""
reports/generate_report.py
Generates a self-contained HTML report from any QA agent report JSON.
Called automatically by orchestrator after each run.

Usage:
    python reports/generate_report.py reports/report.json
    # outputs: reports/report.html
"""

import json
import sys
import os
from pathlib import Path
from html import escape as esc


# ── Helpers ───────────────────────────────────────────────────────────────────

def sev_class(sev: str) -> str:
    return {"critical": "sev-critical", "high": "sev-high",
            "serious": "sev-high", "medium": "sev-medium",
            "low": "sev-low"}.get(str(sev).lower(), "sev-medium")

def border_class(sev: str) -> str:
    return {"critical": "critical", "high": "high",
            "serious": "serious", "medium": "medium",
            "low": "low"}.get(str(sev).lower(), "medium")

def status_color(status: str) -> str:
    return {"FAIL": "var(--red)", "PASS": "var(--green)",
            "WARN": "var(--amber)", "PARTIAL": "var(--amber)"
            }.get(status, "var(--muted)")

def risk_color(risk: str) -> str:
    return {"CRITICAL": "var(--red)", "HIGH": "var(--red)",
            "MEDIUM": "var(--amber)", "LOW": "var(--green)"
            }.get(risk, "var(--muted)")

def action_color(action: str) -> str:
    return {"BLOCK": "var(--red)", "WARN": "var(--amber)",
            "PASS": "var(--green)"}.get(action, "var(--muted)")

def score_color(score: float) -> str:
    if score >= 0.75: return "var(--green)"
    if score >= 0.5:  return "var(--amber)"
    return "var(--red)"

def pct(score: float) -> str:
    return f"{int(score * 100)}%"

def fmt_score(score: float) -> str:
    return f"{score:.2f}"

def browser_icon(name: str) -> str:
    n = name.lower()
    if "firefox" in n: return "🦊"
    if "safari" in n:  return "🧭"
    if "iphone" in n or "ios" in n: return "📱"
    if "pixel" in n or "android" in n: return "📱"
    if "tablet" in n or "ipad" in n: return "📱"
    return "🌐"

def healing_level_class(level: str) -> str:
    l = level.upper()
    if "PRIMARY"   in l: return "level-primary"
    if "SECONDARY" in l: return "level-secondary"
    if "HEURISTIC" in l: return "level-heuristic"
    if "AI"        in l: return "level-ai"
    if "CACHE"     in l: return "level-cache"
    return "level-primary"

def party_cat_class(cat: str) -> str:
    c = str(cat).lower()
    if "cmp"       in c: return "cat-cmp"
    if "analytic"  in c: return "cat-analytics"
    if "advertis"  in c: return "cat-advertising"
    if "tag"       in c: return "cat-tag"
    return "cat-other"

def trace_dot_class(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["fail", "critical", "block", "veto", "error"]):
        return "dot-fail"
    if any(w in t for w in ["warn", "review", "spread", "partial"]):
        return "dot-warn"
    if any(w in t for w in ["healed", "healing", "self-heal"]):
        return "dot-info"
    if any(w in t for w in ["pass", "ok", "clean", "success"]):
        return "dot-ok"
    return "dot-info"


# ── Section builders ──────────────────────────────────────────────────────────

def build_violations_tab(violations: list, evaluator: str,
                          reasoning: str = "", extras: dict = None) -> str:
    if not violations:
        return '<div class="empty-state">No violations detected by this evaluator.</div>'

    html = ""
    for i, v in enumerate(violations):
        sev  = v.get("severity", "medium")
        conf = v.get("confidence", 0)
        html += f"""
        <div class="violation {border_class(sev)}" style="animation-delay:{0.05*i}s">
          <div class="violation-header">
            <span class="sev-tag {sev_class(sev)}">{esc(sev.upper())}</span>
            <span class="violation-rule">{esc(v.get('rule',''))}</span>
          </div>
          <div class="violation-finding">{esc(v.get('finding',''))}</div>
          <div class="violation-evidence">{esc(str(v.get('evidence','—')))}</div>
          <div class="confidence-row">
            <span class="conf-label">confidence</span>
            <div class="conf-track"><div class="conf-fill" style="width:{int(conf*100)}%"></div></div>
            <span class="conf-val">{conf:.2f}</span>
          </div>
        </div>"""

    if extras:
        for label, value in extras.items():
            color = "var(--green)" if value is True else (
                    "var(--red)" if value is False else "var(--muted)")
            html += f"""
        <div class="extras-row">
          <span class="extras-label">{esc(label.replace('_',' '))}</span>
          <span style="font-family:var(--mono);font-size:12px;color:{color}">
            {'✓ yes' if value is True else ('✗ no' if value is False else esc(str(value)))}
          </span>
        </div>"""

    if reasoning:
        html += f"""
        <div class="reasoning-box">
          <div class="reasoning-label">{esc(evaluator.upper())} EVALUATOR REASONING</div>
          <div class="reasoning-text">{esc(reasoning)}</div>
        </div>"""

    return html


def build_cross_browser(cross: dict) -> str:
    if not cross:
        return '<div class="empty-state">Only primary browser tested.</div>'
    html = '<div class="browser-grid">'
    for name, data in cross.items():
        pre = data.get("pre_consent_cookies", {})
        banner = data.get("banner_found", False)
        reject = data.get("reject_found", False)
        has_tracking = bool(pre)
        status_col = "var(--red)" if has_tracking else "var(--green)"
        status_txt = f"{len(pre)} tracking" if has_tracking else "clean"
        html += f"""
        <div class="browser-card">
          <span class="browser-icon">{browser_icon(name)}</span>
          <div class="browser-name">{esc(name)}</div>
          <div class="browser-status" style="color:{status_col}">{esc(status_txt)}</div>
          <div class="browser-sub">
            banner: {'✓' if banner else '✗'} &nbsp;
            reject: {'✓' if reject else '✗'} &nbsp;
            {esc(data.get('banner_format','?')[:3].upper())}
          </div>
        </div>"""
    html += '</div>'
    return html


def build_fourth_parties(fp: dict) -> str:
    domains = fp.get("domains", {})
    if not domains:
        return '<div class="empty-state">No third parties detected.</div>'
    html = ""
    for domain, info in domains.items():
        cat   = info.get("category", "unknown")
        by    = info.get("loaded_by", "direct")
        is4th = info.get("is_fourth_party", False)
        count = info.get("request_count", 0)
        html += f"""
        <div class="party-row">
          <div class="party-domain">{esc(domain)}</div>
          <span class="party-cat {party_cat_class(cat)}">{esc(cat)}</span>
          {'<span class="party-4th">4th party via '+esc(by)+'</span>' if is4th else
           '<span style="font-family:var(--mono);font-size:10px;color:var(--green)">direct</span>'}
          <span class="party-count">{count}req</span>
        </div>"""

    new_domains = fp.get("new_since_baseline", [])
    if new_domains:
        html += f"""
        <div class="new-domains-warning">
          ⚠ New domains since last baseline: {esc(', '.join(new_domains))}
        </div>"""
    return html


def build_healing_events(events: list) -> str:
    if not events:
        return '<div class="empty-state">No self-healing required — all primary selectors found.</div>'
    html = ""
    for e in events:
        level   = e.get("level", "?")
        sel     = e.get("selector", "")
        success = e.get("success", False)
        elem    = e.get("element", "")
        html += f"""
        <div class="healing-event">
          <span class="healing-level {healing_level_class(level)}">{esc(level)}</span>
          <span class="healing-selector" title="{esc(elem)}">{esc(sel[:60])}{'…' if len(sel)>60 else ''}</span>
          <span class="healing-result {'result-ok' if success else 'result-fail'}">
            {'found' if success else 'miss'}
          </span>
        </div>"""

    # Show any reasoning / compliance flags
    flagged = [e for e in events if e.get("compliance_impact")]
    if flagged:
        html += '<div class="healing-warning">⚠ Compliance-impacting layout changes detected — human review required for healed selectors.</div>'
    return html


def build_penalties(penalties: list) -> str:
    if not penalties:
        return '<div class="empty-state">No penalties.</div>'
    html = ""
    for p in penalties:
        if isinstance(p, (list, tuple)):
            check  = str(p[0]) if len(p) > 0 else ""
            w      = float(p[1]) if len(p) > 1 else 0
            detail = str(p[2]) if len(p) > 2 else ""
            crit   = bool(p[3]) if len(p) > 3 else False
            adv    = False
        else:
            w      = float(p.get("weight", 0))
            check  = str(p.get("check", ""))
            detail = str(p.get("detail", ""))
            crit   = bool(p.get("critical", False))
            adv    = bool(p.get("advisory", False))
        color   = "var(--red)" if crit else ("var(--muted)" if adv else "var(--amber)")
        prefix  = "-" if w > 0 else ""
        html += f"""
        <div class="penalty-row" style="border-color:{color}20;background:{color}08">
          <div>
            <div style="font-family:var(--mono);font-size:11px;color:var(--text)">{esc(check)}</div>
            <div style="font-size:12px;color:var(--muted);margin-top:3px">{esc(detail)}</div>
          </div>
          <span style="font-family:var(--mono);font-size:14px;font-weight:700;color:{color}">
            {prefix}{w:.2f}
          </span>
        </div>"""
    return html


def build_voting_bars(voting: dict) -> str:
    scores = voting.get("scores_per_evaluator", {})
    confs  = voting.get("confidences_per_evaluator", {})
    weights = {"compliance": 0.5, "accessibility": 0.3, "ux": 0.2}
    colors  = {"compliance": "var(--red)", "accessibility": "var(--amber)", "ux": "var(--accent2)"}
    html = ""
    for key in ["compliance", "accessibility", "ux"]:
        score = scores.get(key, 0)
        conf  = confs.get(key, 0)
        w     = weights.get(key, 0)
        col   = colors.get(key, "var(--muted)")
        pct_w = int((score / 5) * 100)
        html += f"""
        <div class="voting-row">
          <div class="voting-meta">
            <span class="voting-name">{key.capitalize()} <span class="voting-weight">×{w}</span></span>
            <span style="font-family:var(--mono);font-size:11px;color:{col}">{score}/5 · {conf:.2f} conf</span>
          </div>
          <div class="score-bar-track">
            <div class="score-bar-fill" style="width:{pct_w}%;background:{col}"></div>
          </div>
        </div>"""
    return html


def build_scenarios(scenarios: list) -> str:
    if not scenarios:
        return '<div class="empty-state">No scenario results recorded.</div>'

    # Group by group name, preserving order of first occurrence
    groups: dict = {}
    for s in scenarios:
        g = s.get("group", "Other")
        groups.setdefault(g, []).append(s)

    status_color_map = {
        "PASS":    "var(--green)",
        "FAIL":    "var(--red)",
        "PARTIAL": "var(--amber)",
        "SKIP":    "var(--muted)",
    }
    status_icon = {"PASS": "✓", "FAIL": "✗", "PARTIAL": "~", "SKIP": "–"}

    html = ""
    for group_name, items in groups.items():
        html += f"""
        <div class="scenario-group">
          <div class="scenario-group-label">{esc(group_name)}</div>"""
        for s in items:
            st  = s.get("status", "SKIP")
            col = status_color_map.get(st, "var(--muted)")
            ico = status_icon.get(st, "–")
            html += f"""
          <div class="scenario-row">
            <span class="scenario-id">#{s['id']}</span>
            <span class="scenario-status-icon" style="color:{col}">{ico}</span>
            <div class="scenario-content">
              <div class="scenario-title">{esc(s.get('title',''))}</div>
              <div class="scenario-evidence">{esc(s.get('evidence',''))}</div>
            </div>
            <span class="scenario-badge" style="color:{col};border-color:{col}40;background:{col}12">{esc(st)}</span>
          </div>"""
        html += "\n        </div>"

    return html


def build_trace(trace: list) -> str:
    if not trace:
        return '<div class="empty-state">No reasoning trace recorded.</div>'
    html = ""
    for t in trace:
        dc = trace_dot_class(t)
        html += f"""
        <div class="trace-item">
          <div class="trace-dot {dc}"></div>
          <div class="trace-text">{esc(t)}</div>
        </div>"""
    return html


def build_contrast(contrast: dict) -> str:
    if not contrast or "error" in contrast:
        return '<div class="empty-state">Contrast data not available.</div>'
    rej = contrast.get("reject_ratio", 0)
    acc = contrast.get("accept_ratio", 0)
    diff = contrast.get("ratio_diff", 0)
    rej_pass = contrast.get("wcag_aa_reject", False)
    acc_pass = contrast.get("wcag_aa_accept", False)
    rej_col = "var(--green)" if rej_pass else "var(--red)"
    acc_col = "var(--green)" if acc_pass else "var(--red)"

    return f"""
    <div class="contrast-compare">
      <div class="contrast-item">
        <div class="contrast-item-label">Accept button</div>
        <div class="contrast-ratio" style="color:{acc_col}">{acc:.2f}:1</div>
        <div class="contrast-wcag" style="color:{acc_col}">
          {'✓ WCAG AA pass' if acc_pass else '✗ WCAG AA fail'}
        </div>
      </div>
      <div class="contrast-item">
        <div class="contrast-item-label">Reject button</div>
        <div class="contrast-ratio" style="color:{rej_col}">{rej:.2f}:1</div>
        <div class="contrast-wcag" style="color:{rej_col}">
          {'✓ WCAG AA pass' if rej_pass else f'✗ WCAG AA fail (need 4.5)'}
        </div>
      </div>
    </div>
    {'<div class="dark-pattern-warning">Ratio difference of <strong style=\\"color:var(--red)\\">' +
     str(round(diff,2)) + ' points</strong> between accept and reject — possible EDPB dark pattern.</div>'
     if diff > 1.5 else ''}"""


# ── Main generator ────────────────────────────────────────────────────────────

def generate(report: dict) -> str:
    meta       = report.get("meta", {})
    final      = report.get("final", {})
    det        = report.get("deterministic", {})
    ai         = report.get("ai_evaluations", {})
    voting     = report.get("voting", {})
    healing    = report.get("self_healing", {})
    rules      = report.get("compliance_rules", {})
    scenarios  = report.get("scenario_results", [])

    run_id     = meta.get("run_id", "unknown")
    timestamp  = meta.get("timestamp", "")
    url        = meta.get("target_url", "")
    duration   = meta.get("duration_ms", 0)
    tokens     = meta.get("tokens_used", 0)
    sources    = meta.get("compliance_rules_source", [])
    heal_evts  = meta.get("self_healing_events", []) or healing.get("events", [])
    errors     = meta.get("errors", [])

    status     = final.get("status", "UNKNOWN")
    score      = final.get("score", 0)
    det_score  = final.get("deterministic_score", det.get("score", 0))
    ai_score   = final.get("ai_score", voting.get("weighted_score", 0))
    confidence = final.get("confidence", 0)
    risk       = final.get("risk", "UNKNOWN")
    action     = final.get("pipeline_action", "WARN")
    human_rev  = final.get("human_review_required", False)
    veto       = final.get("compliance_vetoed", False)
    trace      = final.get("reasoning_trace", [])

    contrast   = det.get("contrast_ratios", {})
    fourth     = det.get("fourth_parties", {})
    cross      = det.get("cross_browser", {})
    axe        = det.get("axe_violations", [])
    cmv2       = det.get("consent_mode_v2", {})
    penalties  = det.get("penalty_breakdown", final.get("deterministic_penalties", []))
    pre_cook   = det.get("pre_consent_cookies", {})

    # Per-evaluator data
    comp_v = ai.get("compliance", {})
    a11y_v = ai.get("accessibility", {})
    ux_v   = ai.get("ux", {})

    # Evaluator tab badge counts
    def vcount(ev): return len(ev.get("violations", []))

    total_crit = voting.get("critical_count", 0)
    total_high = voting.get("high_count", 0)
    vbadge = f"{total_crit} critical · {total_high} high" if total_crit or total_high else "clean"

    # Colors
    sc = status_color(status)
    rc = risk_color(risk)
    ac = action_color(action)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QA Report — {esc(url)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#0a0a0f; --surface:#111118; --surface2:#18181f; --border:#2a2a35;
  --border2:#3a3a48; --text:#e8e8f0; --muted:#7a7a90;
  --accent:#00e5ff; --accent2:#7c4dff;
  --red:#ff4560; --amber:#ffb400; --green:#00e096;
  --mono:'Space Mono',monospace; --sans:'DM Sans',sans-serif;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.6;min-height:100vh}}
body::before{{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px);pointer-events:none;z-index:1000}}
.header{{border-bottom:1px solid var(--border);padding:20px 40px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;background:rgba(10,10,15,0.96);backdrop-filter:blur(12px);z-index:100}}
.logo{{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.15em;text-transform:uppercase;border:1px solid var(--accent);padding:4px 10px;border-radius:2px}}
.run-id{{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:16px}}
.timestamp{{font-family:var(--mono);font-size:11px;color:var(--muted)}}
.blink{{animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes slideIn{{from{{opacity:0;transform:translateX(-8px)}}to{{opacity:1;transform:translateX(0)}}}}
.verdict{{margin:28px 40px;border:1px solid {sc};border-radius:4px;padding:24px 32px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center;background:{sc}0d;position:relative;overflow:hidden;animation:fadeIn .4s ease}}
.verdict::before{{content:'';position:absolute;left:0;top:0;bottom:0;width:4px;background:{sc}}}
.verdict-label{{font-family:var(--mono);font-size:10px;letter-spacing:.2em;color:var(--muted);text-transform:uppercase;margin-bottom:5px}}
.verdict-url{{font-size:17px;font-weight:500;margin-bottom:7px}}
.verdict-meta{{font-family:var(--mono);font-size:11px;color:var(--muted);display:flex;flex-wrap:wrap;gap:20px}}
.verdict-meta span{{color:var(--text)}}
.status-badge{{font-family:var(--mono);font-size:26px;font-weight:700;color:{sc};display:block;letter-spacing:-.02em}}
.action-pill{{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:.12em;padding:4px 10px;border-radius:2px;margin-top:6px;background:{ac}1a;color:{ac};border:1px solid {ac}4d}}
.scores{{margin:0 40px 28px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.score-card{{background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:18px;animation:fadeIn .4s ease backwards}}
.score-label{{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;margin-bottom:10px}}
.score-value{{font-family:var(--mono);font-size:32px;font-weight:700;line-height:1;margin-bottom:8px}}
.score-bar-track{{height:3px;background:var(--border);border-radius:2px;overflow:hidden}}
.score-bar-fill{{height:100%;border-radius:2px;transition:width 1s cubic-bezier(.4,0,.2,1)}}
.score-sub{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:7px}}
.main{{padding:0 40px 60px;display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.section{{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;animation:fadeIn .4s ease backwards}}
.section.full{{grid-column:1/-1}}
.section-header{{padding:12px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;background:var(--surface2)}}
.section-title{{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
.section-badge{{font-family:var(--mono);font-size:10px;padding:2px 8px;border-radius:2px}}
.badge-fail{{background:rgba(255,69,96,.15);color:var(--red);border:1px solid rgba(255,69,96,.25)}}
.badge-warn{{background:rgba(255,180,0,.12);color:var(--amber);border:1px solid rgba(255,180,0,.25)}}
.badge-ok{{background:rgba(0,224,150,.1);color:var(--green);border:1px solid rgba(0,224,150,.2)}}
.badge-info{{background:rgba(0,229,255,.1);color:var(--accent);border:1px solid rgba(0,229,255,.2)}}
.section-body{{padding:18px}}
.tabs{{display:flex;border-bottom:1px solid var(--border);padding:0 18px;background:var(--surface2)}}
.tab{{font-family:var(--mono);font-size:11px;letter-spacing:.06em;color:var(--muted);padding:11px 14px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;transition:color .15s,border-color .15s;text-transform:uppercase;user-select:none}}
.tab:hover{{color:var(--text)}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-content{{display:none}}
.tab-content.active{{display:block}}
.violation{{border-left:3px solid var(--border2);padding:12px 14px;margin-bottom:10px;border-radius:0 4px 4px 0;background:rgba(255,255,255,.02);animation:slideIn .3s ease backwards}}
.violation:last-child{{margin-bottom:0}}
.violation.critical{{border-left-color:var(--red)}}
.violation.high,.violation.serious{{border-left-color:var(--amber)}}
.violation.medium{{border-left-color:#888}}
.violation.low{{border-left-color:#555}}
.violation-header{{display:flex;align-items:flex-start;gap:8px;margin-bottom:6px}}
.sev-tag{{font-family:var(--mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;padding:2px 6px;border-radius:2px;white-space:nowrap;flex-shrink:0}}
.sev-critical{{background:rgba(255,69,96,.2);color:var(--red)}}
.sev-high{{background:rgba(255,180,0,.15);color:var(--amber)}}
.sev-medium{{background:rgba(255,255,255,.08);color:#aaa}}
.sev-low{{background:rgba(255,255,255,.04);color:#666}}
.violation-rule{{font-family:var(--mono);font-size:11px;color:var(--accent);line-height:1.4}}
.violation-finding{{font-size:13px;color:var(--text);line-height:1.5;margin-bottom:6px}}
.violation-evidence{{font-family:var(--mono);font-size:11px;color:var(--muted);background:rgba(0,0,0,.3);padding:6px 10px;border-radius:2px;border:1px solid var(--border);word-break:break-all}}
.confidence-row{{display:flex;align-items:center;gap:8px;margin-top:7px}}
.conf-label{{font-family:var(--mono);font-size:10px;color:var(--muted);width:76px}}
.conf-track{{flex:1;height:2px;background:var(--border);border-radius:2px;overflow:hidden}}
.conf-fill{{height:100%;background:var(--accent);border-radius:2px}}
.conf-val{{font-family:var(--mono);font-size:10px;color:var(--accent);width:34px;text-align:right}}
.reasoning-box{{margin-top:14px;padding:12px 14px;background:rgba(0,229,255,.05);border:1px solid rgba(0,229,255,.15);border-radius:3px}}
.reasoning-label{{font-family:var(--mono);font-size:10px;color:var(--accent);margin-bottom:6px}}
.reasoning-text{{font-size:12px;color:var(--muted);line-height:1.6}}
.extras-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px}}
.extras-row:last-child{{border-bottom:none}}
.extras-label{{color:var(--muted);text-transform:capitalize}}
.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.metric{{background:rgba(0,0,0,.2);border:1px solid var(--border);border-radius:3px;padding:11px 13px}}
.metric-label{{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.06em;margin-bottom:5px}}
.metric-value{{font-family:var(--mono);font-size:15px;font-weight:700}}
.metric-value.ok{{color:var(--green)}}
.metric-value.fail{{color:var(--red)}}
.metric-value.warn{{color:var(--amber)}}
.metric-value.info{{color:var(--accent)}}
.penalty-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:3px;margin-bottom:7px;border:1px solid}}
.contrast-compare{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}}
.contrast-item{{background:rgba(0,0,0,.25);border:1px solid var(--border);border-radius:3px;padding:14px}}
.contrast-item-label{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:7px}}
.contrast-ratio{{font-family:var(--mono);font-size:20px;font-weight:700;margin-bottom:4px}}
.contrast-wcag{{font-family:var(--mono);font-size:10px}}
.dark-pattern-warning{{padding:10px 14px;background:rgba(255,69,96,.06);border:1px solid rgba(255,69,96,.15);border-radius:3px;font-size:12px;color:var(--muted);line-height:1.5}}
.browser-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.browser-card{{background:rgba(0,0,0,.2);border:1px solid var(--border);border-radius:3px;padding:13px;text-align:center}}
.browser-icon{{font-size:22px;margin-bottom:7px;display:block}}
.browser-name{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:5px}}
.browser-status{{font-family:var(--mono);font-size:11px;font-weight:700}}
.browser-sub{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:4px}}
.healing-event{{display:flex;align-items:center;gap:10px;padding:9px 11px;background:rgba(0,0,0,.2);border:1px solid var(--border);border-radius:3px;margin-bottom:7px;font-family:var(--mono);font-size:11px}}
.healing-level{{padding:2px 7px;border-radius:2px;white-space:nowrap;flex-shrink:0;font-size:10px}}
.level-primary{{background:rgba(0,229,255,.12);color:var(--accent);border:1px solid rgba(0,229,255,.2)}}
.level-secondary{{background:rgba(124,77,255,.12);color:var(--accent2);border:1px solid rgba(124,77,255,.2)}}
.level-heuristic{{background:rgba(255,180,0,.12);color:var(--amber);border:1px solid rgba(255,180,0,.2)}}
.level-ai{{background:rgba(255,69,96,.12);color:var(--red);border:1px solid rgba(255,69,96,.2)}}
.level-cache{{background:rgba(0,224,150,.1);color:var(--green);border:1px solid rgba(0,224,150,.2)}}
.healing-selector{{color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.healing-result{{padding:2px 7px;border-radius:2px;font-size:10px;flex-shrink:0}}
.result-ok{{background:rgba(0,224,150,.12);color:var(--green)}}
.result-fail{{background:rgba(255,69,96,.12);color:var(--red)}}
.healing-warning{{margin-top:10px;padding:9px 12px;background:rgba(255,180,0,.06);border:1px solid rgba(255,180,0,.2);border-radius:3px;font-size:12px;color:var(--amber)}}
.party-row{{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}}
.party-row:last-of-type{{border-bottom:none}}
.party-domain{{font-family:var(--mono);font-size:12px;flex:1}}
.party-cat{{font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:2px}}
.party-count{{font-family:var(--mono);font-size:10px;color:var(--muted)}}
.cat-cmp{{background:rgba(0,229,255,.1);color:var(--accent)}}
.cat-analytics{{background:rgba(255,180,0,.1);color:var(--amber)}}
.cat-advertising{{background:rgba(255,69,96,.12);color:var(--red)}}
.cat-tag{{background:rgba(124,77,255,.12);color:var(--accent2)}}
.cat-other{{background:rgba(255,255,255,.06);color:var(--muted)}}
.party-4th{{font-family:var(--mono);font-size:10px;color:var(--red);border:1px solid rgba(255,69,96,.25);padding:2px 6px;border-radius:2px}}
.new-domains-warning{{margin-top:10px;padding:9px 12px;background:rgba(255,69,96,.06);border:1px solid rgba(255,69,96,.2);border-radius:3px;font-size:12px;color:var(--red)}}
.voting-row{{margin-bottom:12px}}
.voting-meta{{display:flex;justify-content:space-between;margin-bottom:5px}}
.voting-name{{font-family:var(--mono);font-size:11px;color:var(--muted)}}
.voting-weight{{color:var(--text)}}
.trace-item{{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}}
.trace-item:last-child{{border-bottom:none}}
.trace-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:5px}}
.dot-fail{{background:var(--red)}}
.dot-warn{{background:var(--amber)}}
.dot-ok{{background:var(--green)}}
.dot-info{{background:var(--accent)}}
.trace-text{{color:var(--text);line-height:1.5}}
.empty-state{{padding:16px;font-family:var(--mono);font-size:11px;color:var(--muted);text-align:center;border:1px dashed var(--border);border-radius:3px}}
.scenario-group{{margin-bottom:18px}}
.scenario-group:last-child{{margin-bottom:0}}
.scenario-group-label{{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid var(--border)}}
.scenario-row{{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:3px;margin-bottom:5px;background:rgba(0,0,0,.15);border:1px solid var(--border)}}
.scenario-row:hover{{background:rgba(255,255,255,.03)}}
.scenario-id{{font-family:var(--mono);font-size:10px;color:var(--muted);width:22px;flex-shrink:0;text-align:right}}
.scenario-status-icon{{font-family:var(--mono);font-size:13px;font-weight:700;width:14px;flex-shrink:0;text-align:center}}
.scenario-content{{flex:1;min-width:0}}
.scenario-title{{font-size:13px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.scenario-evidence{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.scenario-badge{{font-family:var(--mono);font-size:9px;letter-spacing:.1em;padding:2px 7px;border-radius:2px;border:1px solid;white-space:nowrap;flex-shrink:0}}
.errors-section{{margin:0 40px 20px;padding:14px 18px;background:rgba(255,69,96,.08);border:1px solid rgba(255,69,96,.25);border-radius:4px}}
.footer{{border-top:1px solid var(--border);padding:14px 40px;display:flex;justify-content:space-between;align-items:center;font-family:var(--mono);font-size:11px;color:var(--muted)}}
::-webkit-scrollbar{{width:5px;height:5px}}
::-webkit-scrollbar-track{{background:var(--bg)}}
::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:3px}}
</style>
</head>
<body>

<header class="header">
  <div style="display:flex;align-items:center">
    <div class="logo">QA Agent</div>
    <div class="run-id">run // {esc(run_id[:24])}</div>
  </div>
  <div style="display:flex;align-items:center;gap:20px">
    <span class="timestamp">{esc(timestamp[:19].replace('T',' '))} UTC</span>
    <span class="blink" style="color:{ac};font-family:var(--mono);font-size:11px">● {esc(action)}</span>
  </div>
</header>

<div class="verdict">
  <div>
    <div class="verdict-label">Target</div>
    <div class="verdict-url">{esc(url)}</div>
    <div class="verdict-meta">
      <span>Duration: <span>{duration:,}ms</span></span>
      <span>Tokens: <span>{tokens:,}</span></span>
      <span>Format: <span>{esc(det.get('banner_format','unknown').upper())}</span></span>
      <span>Browsers: <span>{1 + len(cross)}</span></span>
      <span>Source: <span>{esc(sources[0].split('/')[2] if sources else 'hardcoded')}</span></span>
    </div>
  </div>
  <div style="text-align:right">
    <span class="status-badge">{esc(status)}</span>
    <span class="action-pill">{'⛔' if action=='BLOCK' else ('⚠' if action=='WARN' else '✓')} {esc(action)} PIPELINE</span>
    <div style="margin-top:8px;font-family:var(--mono);font-size:10px;color:var(--muted)">
      Risk: <span style="color:{rc}">{esc(risk)}</span>
      {'&nbsp;·&nbsp;<span style="color:var(--amber)">⚠ human review</span>' if human_rev else ''}
    </div>
  </div>
</div>

{"<div class='errors-section'><div style='font-family:var(--mono);font-size:10px;color:var(--red);margin-bottom:8px'>ERRORS DURING RUN</div>" + "".join(f"<div style='font-size:12px;color:var(--muted);margin-bottom:4px'>{esc(e)}</div>" for e in errors) + "</div>" if errors else ""}

<div class="scores">
  <div class="score-card" style="animation-delay:.05s">
    <div class="score-label">Final Score</div>
    <div class="score-value" style="color:{score_color(score)}">{fmt_score(score)}</div>
    <div class="score-bar-track"><div class="score-bar-fill" style="width:{pct(score)};background:{score_color(score)}"></div></div>
    <div class="score-sub">Det×0.6 + AI×0.4</div>
  </div>
  <div class="score-card" style="animation-delay:.10s">
    <div class="score-label">Deterministic</div>
    <div class="score-value" style="color:{score_color(det_score)}">{fmt_score(det_score)}</div>
    <div class="score-bar-track"><div class="score-bar-fill" style="width:{pct(det_score)};background:{score_color(det_score)}"></div></div>
    <div class="score-sub">Playwright facts</div>
  </div>
  <div class="score-card" style="animation-delay:.15s">
    <div class="score-label">AI Weighted</div>
    <div class="score-value" style="color:{score_color(ai_score)}">{fmt_score(ai_score)}</div>
    <div class="score-bar-track"><div class="score-bar-fill" style="width:{pct(ai_score)};background:{score_color(ai_score)}"></div></div>
    <div class="score-sub">Claude reasoning</div>
  </div>
  <div class="score-card" style="animation-delay:.20s">
    <div class="score-label">Confidence</div>
    <div class="score-value" style="color:{score_color(confidence)}">{fmt_score(confidence)}</div>
    <div class="score-bar-track"><div class="score-bar-fill" style="width:{pct(confidence)};background:{score_color(confidence)}"></div></div>
    <div class="score-sub">{'High — reliable' if confidence>=0.85 else ('Medium — review' if confidence>=0.6 else 'Low — unreliable')}</div>
  </div>
</div>

<div class="main">

  <!-- Feature Coverage -->
  {"" if not scenarios else f"""
  <div class="section full" style="animation-delay:.08s">
    <div class="section-header">
      <span class="section-title">Feature Coverage — cookie_consent.feature</span>
      <span class="section-badge {
          'badge-fail' if sum(1 for s in scenarios if s['status']=='FAIL') > 0
          else 'badge-warn' if sum(1 for s in scenarios if s['status']=='PARTIAL') > 0
          else 'badge-ok'
      }">
        {sum(1 for s in scenarios if s['status']=='PASS')} pass &nbsp;·&nbsp;
        {sum(1 for s in scenarios if s['status']=='FAIL')} fail &nbsp;·&nbsp;
        {sum(1 for s in scenarios if s['status']=='PARTIAL')} partial &nbsp;·&nbsp;
        {sum(1 for s in scenarios if s['status']=='SKIP')} skip
      </span>
    </div>
    <div class="section-body">{build_scenarios(scenarios)}</div>
  </div>"""}

  <!-- Violations -->
  <div class="section full" style="animation-delay:.10s">
    <div class="section-header">
      <span class="section-title">AI Evaluator Violations</span>
      <span class="section-badge {'badge-fail' if total_crit else ('badge-warn' if total_high else 'badge-ok')}">{esc(vbadge)}</span>
    </div>
    <div class="tabs">
      <div class="tab active" onclick="showTab('t-compliance',this)">Compliance ({vcount(comp_v)})</div>
      <div class="tab" onclick="showTab('t-a11y',this)">Accessibility ({vcount(a11y_v)})</div>
      <div class="tab" onclick="showTab('t-ux',this)">UX / Dark patterns ({vcount(ux_v)})</div>
    </div>
    <div id="t-compliance" class="tab-content active section-body">
      {build_violations_tab(
          comp_v.get('violations',[]), 'compliance',
          comp_v.get('reasoning',''),
          {'compliant': comp_v.get('compliant')}
      )}
    </div>
    <div id="t-a11y" class="tab-content section-body">
      {build_violations_tab(
          a11y_v.get('violations',[]), 'accessibility',
          a11y_v.get('reasoning',''),
          {'keyboard navigable': a11y_v.get('keyboard_navigable'),
           'screen reader compatible': a11y_v.get('screen_reader_compatible')}
      )}
    </div>
    <div id="t-ux" class="tab-content section-body">
      {build_violations_tab(
          ux_v.get('violations',[]), 'ux',
          ux_v.get('reasoning',''),
          {'accept reject prominence equal': ux_v.get('accept_reject_prominence_equal')}
      )}
    </div>
  </div>

  <!-- Deterministic -->
  <div class="section" style="animation-delay:.15s">
    <div class="section-header">
      <span class="section-title">Deterministic Layer</span>
      <span class="section-badge {'badge-fail' if det_score<0.6 else ('badge-warn' if det_score<0.8 else 'badge-ok')}">score: {fmt_score(det_score)}</span>
    </div>
    <div class="section-body">
      <div class="metrics">
        <div class="metric">
          <div class="metric-label">Pre-consent cookies</div>
          <div class="metric-value {'fail' if pre_cook else 'ok'}">{f"{len(pre_cook)} found" if pre_cook else "✓ none"}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Reject button</div>
          <div class="metric-value {'ok' if det.get('reject_button_found') else 'fail'}">{'✓ present' if det.get('reject_button_found') else '✗ missing'}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Consent Mode v2</div>
          <div class="metric-value {'ok' if cmv2.get('ad_storage_default_denied') else ('warn' if cmv2.get('detected') else 'info')}">{'✓ correct' if cmv2.get('ad_storage_default_denied') else ('✗ wrong defaults' if cmv2.get('detected') else 'not detected')}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Fourth parties</div>
          <div class="metric-value {'warn' if fourth.get('fourth_parties') else 'ok'}">{len(fourth.get('fourth_parties',[])) or '✓ none'}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Axe violations</div>
          <div class="metric-value {'fail' if any(v.get('impact')=='critical' for v in axe) else ('warn' if axe else 'ok')}">{f"{len(axe)} found" if axe else "✓ none"}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Banner found</div>
          <div class="metric-value {'ok' if det.get('primary_context',{}).get('banner_found') else 'fail'}">{'✓ yes' if det.get('primary_context',{}).get('banner_found') else '✗ no'}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Banner format</div>
          <div class="metric-value info">{esc(det.get('banner_format', 'unknown').upper())}</div>
        </div>
      </div>
      {"<div style='margin-top:14px'><div style='font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.1em;text-transform:uppercase;margin-bottom:9px'>Penalty breakdown</div>" + build_penalties(penalties) + "</div>" if penalties else ""}
    </div>
  </div>

  <!-- Contrast -->
  <div class="section" style="animation-delay:.20s">
    <div class="section-header">
      <span class="section-title">Contrast Analysis</span>
      <span class="section-badge {'badge-fail' if not contrast.get('wcag_aa_reject',True) else 'badge-ok'}">{'dark pattern detected' if (contrast.get('ratio_diff',0) or 0)>1.5 else 'ok'}</span>
    </div>
    <div class="section-body">{build_contrast(contrast)}</div>
  </div>

  <!-- Cross-browser -->
  <div class="section" style="animation-delay:.25s">
    <div class="section-header">
      <span class="section-title">Cross-browser Results</span>
      <span class="section-badge badge-info">{1+len(cross)} browsers tested</span>
    </div>
    <div class="section-body">{build_cross_browser(cross)}</div>
  </div>

  <!-- Self-healing -->
  <div class="section" style="animation-delay:.30s">
    <div class="section-header">
      <span class="section-title">Self-healing Events</span>
      <span class="section-badge {'badge-warn' if heal_evts else 'badge-ok'}">strategy: {esc(healing.get('strategy','NONE'))}</span>
    </div>
    <div class="section-body">{build_healing_events(heal_evts)}</div>
  </div>

  <!-- Fourth parties -->
  <div class="section" style="animation-delay:.35s">
    <div class="section-header">
      <span class="section-title">Third / Fourth Party Scan</span>
      <span class="section-badge {'badge-warn' if fourth.get('fourth_parties') else 'badge-ok'}">{len(fourth.get('fourth_parties',[]))} fourth parties</span>
    </div>
    <div class="section-body">{build_fourth_parties(fourth)}</div>
  </div>

  <!-- Voting -->
  <div class="section" style="animation-delay:.40s">
    <div class="section-header">
      <span class="section-title">Multi-evaluator Voting</span>
      <span class="section-badge {'badge-fail' if veto else 'badge-info'}">{'compliance veto' if veto else 'no veto'}</span>
    </div>
    <div class="section-body">
      {build_voting_bars(voting)}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px">
        <div style="padding:10px 12px;background:{'rgba(255,69,96,.08)' if veto else 'rgba(0,224,150,.06)'};border:1px solid {'rgba(255,69,96,.2)' if veto else 'rgba(0,224,150,.15)'};border-radius:3px;font-family:var(--mono);font-size:11px">
          <div style="color:var(--muted);margin-bottom:4px">Compliance veto</div>
          <div style="color:{'var(--red)' if veto else 'var(--green)'}">{'TRIGGERED' if veto else 'CLEAR'}</div>
        </div>
        <div style="padding:10px 12px;background:{'rgba(255,180,0,.06)' if human_rev else 'rgba(0,224,150,.06)'};border:1px solid {'rgba(255,180,0,.2)' if human_rev else 'rgba(0,224,150,.15)'};border-radius:3px;font-family:var(--mono);font-size:11px">
          <div style="color:var(--muted);margin-bottom:4px">Human review</div>
          <div style="color:{'var(--amber)' if human_rev else 'var(--green)'}">{'REQUIRED' if human_rev else 'NOT REQUIRED'}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Trace -->
  <div class="section" style="animation-delay:.45s">
    <div class="section-header">
      <span class="section-title">Reasoning Trace</span>
      <span class="section-badge badge-info">pipeline: {esc(action)}</span>
    </div>
    <div class="section-body">{build_trace(trace)}</div>
  </div>

</div>

<footer class="footer">
  <span>QA Agent v1.0 · Playwright + Claude · temp=0</span>
  <span>Rules: {esc(' · '.join(sources[:2]))}</span>
  <span>run/{esc(run_id[:12])}</span>
</footer>

<script>
function showTab(id,el){{
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  el.classList.add('active');
}}
window.addEventListener('load',()=>{{
  document.querySelectorAll('.score-bar-fill').forEach(b=>{{
    const w=b.style.width; b.style.width='0%';
    setTimeout(()=>{{b.style.width=w;}},150);
  }});
}});
</script>
</body>
</html>"""
    return html


# ── CLI entry + module API ────────────────────────────────────────────────────

def generate_from_file(json_path: str) -> str:
    """Generate HTML from a report JSON file. Returns output HTML path."""
    with open(json_path) as f:
        report = json.load(f)
    html = generate(report)
    out_path = str(json_path).replace(".json", ".html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def generate_from_dict(report: dict, output_path: str) -> str:
    """Generate HTML from a report dict. Returns output HTML path."""
    html = generate(report)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reports/generate_report.py <report.json>")
        sys.exit(1)
    out = generate_from_file(sys.argv[1])
    print(f"Report written to: {out}")
