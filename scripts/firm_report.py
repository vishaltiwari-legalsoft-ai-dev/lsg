"""One firm's enrichment report as a PDF: what came in, what the engine did,
everything it sighted (with the source of each fact), every review, the pain
analysis, where it stopped and why, what it cost, and the full email
journey it would send. Built from the store, never from memory.

    .venv\\Scripts\\python.exe scripts\\firm_report.py <firm_id> [--subject "..."]
        [--assume-fee flat] [--out .local/reports]

Renders HTML, then prints it to PDF with the installed Chrome (headless).
"""
# ruff: noqa: E501 -- the page's markup and style sheet are long lines by nature

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from lge import db as lge_db
from lge.export.list import fetch_journey_edits
from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyLead, Signal
from lge.journey.render import sender_missing, signature
from lge.journey.usp import cta_html
from lge.settings import PROJECT_ROOT

CHROME_CANDIDATES = [
    os.environ.get("LGE_CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

PAIN_TO_SIGNAL = {
    "calls_unreturned": "review_unreturned_call",
    "review_complaint": "review_unreturned_call",
    "job_posting_open": "job_posting_open",
    "multi_opening": "multi_opening",
    "cms_implemented": "cms_implemented",
}
STEP_WORDS = {
    "p1_site_map": "Mapped the site: robots.txt, sitemap, the page kinds worth reading",
    "p2_fetch": "Fetched the pages into the store",
    "p3_render": "Rendered JavaScript shells where a page was empty",
    "p4_text": "Extracted the text of every page",
    "p5_jsonld": "Read the structured data the site publishes",
    "p6_fee": "Looked for a stated fee model",
    "p7_tech": "Detected the case-management and website tools",
    "px_site_rules": "Applied the site rules (staff counts, gaps, intake form)",
    "px_site_facts": "Wrote the site facts as claims",
    "p8_llm": "AI reading of the whole site (Claude Haiku 4.5)",
    "p9_escalate": "AI second reading, escalated (Claude Opus 5)",
    "reconcile": "Reconciled every claim onto the firm's record",
    "r_site_contacts": "People named on the site",
    "r_site_emails": "Addresses printed on the site",
    "r_listing": "Google Business Profile and its reviews (Serper)",
    "r_search_links": "LinkedIn profiles and company page (Serper)",
    "r_search_emails": "Addresses found in search results (Serper)",
    "r3_email_pattern": "The firm's email pattern, learned from known addresses",
    "r_email_guess": "Addresses worked out from name and domain (NeverBounce)",
    "r4_verify": "Address verification (NeverBounce)",
    "classify": "Classified the lead by fee model and practice",
    "ja1_careers": "Read the careers page for openings",
    "ja6_normalise": "Normalised job postings",
    "ja6_closure": "Closed postings that came down",
    "ja7_pain_signals": "Opened pain signals from fixed rules",
    "ja8_pain": "AI pain analysis over the whole record (Claude Haiku 4.5)",
    "score": "Scored fit and intent",
    "website_check": "Checked the website answers and names the firm",
}


def q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def one(conn, sql, params=()):
    rows = q(conn, sql, params)
    return rows[0] if rows else None


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def fmt_date(v) -> str:
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d %b %Y")
    return str(v)[:10]


def collect(conn, firm_id: str) -> dict:
    d: dict = {}
    d["firm"] = one(conn, "SELECT * FROM firm WHERE id = %s", (firm_id,))
    if d["firm"] is None:
        sys.exit(f"no firm {firm_id}")
    d["observations"] = q(conn, "SELECT * FROM observation WHERE firm_id = %s ORDER BY fetched_at",
                          (firm_id,))
    d["claims"] = q(conn, "SELECT attr, source, confidence, value, evidence, observed_at "
                          "FROM firm_attribute WHERE firm_id = %s ORDER BY attr, observed_at DESC",
                    (firm_id,))
    d["contacts"] = q(conn, "SELECT * FROM contact WHERE firm_id = %s AND removed_at IS NULL "
                            "ORDER BY (role = 'owner') DESC, full_name", (firm_id,))
    ids = [c["id"] for c in d["contacts"]]
    d["emails"] = q(conn, "SELECT e.*, c.full_name FROM contact_email e JOIN contact c ON c.id = "
                          "e.contact_id WHERE e.contact_id = ANY(%s) ORDER BY c.full_name, e.email",
                    (ids,)) if ids else []
    d["pages"] = q(conn, "SELECT page_kind, url, status_code, fetch_ok, word_count, fetched_at "
                         "FROM document WHERE firm_id = %s ORDER BY page_kind, url", (firm_id,))
    d["searches"] = q(conn, "SELECT kind, outcome, engine, query, url, rating, review_count, "
                            "searched_at FROM search_log WHERE firm_id = %s ORDER BY searched_at",
                      (firm_id,))
    d["webchecks"] = q(conn, "SELECT * FROM website_check WHERE firm_id = %s ORDER BY checked_at",
                       (firm_id,))
    d["ai"] = q(conn, "SELECT component, model, prompt_rev, status, input_tokens, output_tokens, "
                      "cost_usd, created_at FROM llm_call WHERE firm_id = %s ORDER BY created_at",
                (firm_id,))
    d["verify"] = q(conn, "SELECT v.* FROM verify_attempt v WHERE v.email = ANY(%s) "
                          "ORDER BY created_at", ([e["email"] for e in d["emails"]],)) \
        if d["emails"] else []
    d["lead"] = one(conn, "SELECT * FROM lead WHERE firm_id = %s AND closed_at IS NULL "
                          "ORDER BY created_at DESC LIMIT 1", (firm_id,))
    d["history"] = q(conn, "SELECT * FROM lead_state_event WHERE lead_id = %s ORDER BY at",
                     (d["lead"]["id"],)) if d["lead"] else []
    d["signals"] = q(conn, "SELECT * FROM signal WHERE firm_id = %s ORDER BY first_seen",
                     (firm_id,))
    d["runs"] = q(conn, "SELECT component, status, started_at, finished_at FROM task_run "
                        "WHERE entity_id = %s ORDER BY started_at", (firm_id,))
    return d


def latest_claim(claims, attr, source_prefix=None):
    for c in claims:
        if c["attr"] == attr and (source_prefix is None or c["source"].startswith(source_prefix)):
            return c
    return None


def render_journey(d: dict, subject_override: str | None, assume_fee: str | None) -> dict:
    firm, lead = d["firm"], d["lead"]
    owner = next((c for c in d["contacts"] if c["role"] == "owner"), None) or (
        d["contacts"][0] if d["contacts"] else None)
    pain = latest_claim(d["claims"], "pain_analysis")
    pains = (pain["value"] or {}).get("pains", []) if pain else []
    kind = next((PAIN_TO_SIGNAL[p["kind"]] for p in pains if p["kind"] in PAIN_TO_SIGNAL), None)
    live_signal = next((s for s in d["signals"] if s["closed_at"] is None
                        and s["kind"] in PAIN_TO_SIGNAL.values()), None)
    assumptions: list[str] = []
    fee = firm["fee_model"]
    if fee in (None, "unknown", "mixed") and assume_fee:
        assumptions.append(
            f"Fee model assumed '{assume_fee}' for this rendering: the site never states one, "
            "and the engine itself holds the lead until it is set."
        )
        fee = assume_fee
    tier = firm["tier"]
    if tier in (None, "UNCLASSIFIED") and assume_fee:
        tier = "1B" if (firm["primary_practice"] or "") in ("immigration", "family") else "3"
        assumptions.append(f"Tier assumed '{tier}' from the practice, for the same reason.")
    now = datetime.now(UTC)
    if live_signal is not None:
        sig = Signal(id=live_signal["id"], kind=live_signal["kind"],
                     first_seen=live_signal["first_seen"], last_seen=live_signal["last_seen"],
                     closed_at=None, repost_count=live_signal["repost_count"] or 0,
                     evidence=live_signal["evidence"] or {})
    elif kind:
        sig = Signal(id=0, kind=kind, first_seen=now, last_seen=now, closed_at=None,
                     repost_count=0, evidence={"reviews": len(pains)})
        assumptions.append(
            "The arming signal is taken from the AI pain analysis (calls unreturned in the "
            "reviews); today the engine opens that signal only from its fixed rules."
        )
    else:
        sig = None
    if not owner:
        return {"touches": [], "excluded": "no decision-maker on record", "assumptions": assumptions}
    jl = JourneyLead(
        lead_id=str(lead["id"]) if lead else "none", band="SEQUENCE",
        firm=Firm(id=str(firm["id"]), canonical_name=firm["canonical_name"], city=firm["city"],
                  state=firm["state"], tier=tier or "3", fee_model=fee,
                  primary_practice=firm["primary_practice"], cms_detected=firm["cms_detected"]),
        contact=Contact(id=str(owner["id"]), full_name=owner["full_name"], title=owner["title"],
                        role=owner["role"]),
        signal=sig, repost_first_seen=None, at=now,
    )
    with lge_db.connect() as conn:
        result = build_journey(jl, fetch_journey_edits(conn))
    touches = []
    sig = signature()
    for t in result.touches:
        subject = t.subject
        if t.step == 1 and subject_override:
            subject = subject_override
        copy = t.body
        for block in (sig, t.cta, t.usp):
            if block and block in copy:
                copy = copy[: copy.index(block)].rstrip("\n")
        touches.append({"step": t.step, "day": t.day, "subject": subject, "body": t.body,
                        "copy": copy, "usp": t.usp, "cta": t.cta})
    return {"touches": touches, "excluded": result.excluded_reason, "assumptions": assumptions,
            "signature": signature(), "sender_missing": sender_missing(), "band": "SEQUENCE"}


def build_html(d: dict, journey: dict, subject_override: str | None) -> str:
    f = d["firm"]
    claims = d["claims"]
    listing = latest_claim(claims, "business_listing")
    listing_v = (listing["value"] if listing else {}) or {}
    reviews_c = latest_claim(claims, "google_reviews")
    reviews = (reviews_c["value"] if reviews_c else []) or []
    pain = latest_claim(claims, "pain_analysis")
    pain_v = (pain["value"] if pain else {}) or {}
    gaps = latest_claim(claims, "site_gaps")
    gaps_v = (gaps["value"] if gaps else []) or []
    obs = d["observations"][0] if d["observations"] else None
    raw = ((obs["payload"] or {}).get("_raw") or {}) if obs else {}
    serper = sum(1 for s in d["searches"] if s["engine"] == "serper")
    listing_calls = sum(2 for s in d["searches"] if s["kind"] == "listing" and s["outcome"] == "found")
    ai_cost = sum(float(a["cost_usd"] or 0) for a in d["ai"])
    nb_cost = sum(float(v["cost_usd"] or 0) for v in d["verify"])
    lead = d["lead"]
    today = datetime.now().strftime("%d %B %Y")

    def row(k, v, src=""):
        return f"<tr><th>{esc(k)}</th><td>{v}</td><td class='src'>{esc(src)}</td></tr>"

    def source_of(attr):
        c = latest_claim(claims, attr)
        return c["source"] if c else ""

    parts: list[str] = []
    parts.append(f"""
<header class="cover">
  <p class="kicker">Lead Gen Engine · enrichment report</p>
  <h1>{esc(f['canonical_name'])}</h1>
  <p class="sub">{esc(f['city'] or '')}{', ' + esc(f['state']) if f['state'] else ''} · {esc(f['domain'] or 'no website')}</p>
  <p class="meta">What came in, what the engine did, everything it sighted, and the emails it would send. Prepared {today}. Every fact below carries where it came from.</p>
</header>""")

    # 1 · at a glance
    pains = pain_v.get("pains", [])
    headline = pains[0]["headline"] if pains else "No proven pain yet"
    parts.append(f"""
<section>
  <h2>1 · At a glance</h2>
  <div class="glance">
    <div><span class="n">{len(d['pages'])}</span><span class="l">pages read</span></div>
    <div><span class="n">{len(reviews)}</span><span class="l">reviews read</span></div>
    <div><span class="n">{len(pains)}</span><span class="l">pains proven</span></div>
    <div><span class="n">{len(d['contacts'])}</span><span class="l">people</span></div>
    <div><span class="n">{serper}</span><span class="l">Serper credits</span></div>
    <div><span class="n">${ai_cost:.3f}</span><span class="l">AI spend</span></div>
  </div>
  <p class="verdict"><strong>The pain to target:</strong> {esc(headline)}.</p>
  <p class="verdict"><strong>Chosen subject for email 1:</strong> {esc(subject_override or (journey['touches'][0]['subject'] if journey['touches'] else ''))}</p>
</section>""")

    # 2 · what came in
    parts.append("<section><h2>2 · What came in from the sheet</h2><table class='kv'>")
    if raw:
        for k, v in raw.items():
            if v not in (None, "", "None"):
                parts.append(row(k, esc(v), "sheet"))
    parts.append("</table></section>")

    # 3 · what the engine did
    parts.append("<section><h2>3 · What the engine did</h2><table class='grid'>"
                 "<tr><th>When</th><th>Step</th><th>What happened</th></tr>")
    seen = set()
    for r in d["runs"]:
        key = (r["component"], fmt_date(r["started_at"]))
        if key in seen:
            continue
        seen.add(key)
        words = STEP_WORDS.get(r["component"], r["component"])
        parts.append(f"<tr><td>{fmt_date(r['started_at'])}</td><td>{esc(r['component'])}</td>"
                     f"<td>{esc(words)} — {esc(r['status'])}</td></tr>")
    for s in d["searches"]:
        parts.append(f"<tr><td>{fmt_date(s['searched_at'])}</td><td>search · {esc(s['kind'])}</td>"
                     f"<td>{esc(s['engine'])}: {esc(s['outcome'])} — <span class='q'>{esc(s['query'])}</span></td></tr>")
    for a in d["ai"]:
        parts.append(f"<tr><td>{fmt_date(a['created_at'])}</td><td>AI · {esc(a['component'])}</td>"
                     f"<td>{esc(a['model'])} ({esc(a['prompt_rev'])}): {esc(a['status'])}, "
                     f"{a['input_tokens'] or 0} in / {a['output_tokens'] or 0} out, ${float(a['cost_usd'] or 0):.4f}</td></tr>")
    for w in d["webchecks"]:
        parts.append(f"<tr><td>{fmt_date(w['checked_at'])}</td><td>website check</td>"
                     f"<td>{esc(w['outcome'])}{': ' + esc(w['note']) if w['note'] else ''}</td></tr>")
    parts.append("</table></section>")

    # 4 · what it found
    parts.append("<section><h2>4 · What the engine found</h2><h3>The firm</h3><table class='kv'>")
    parts.append(row("Name", esc(f["canonical_name"]), source_of("canonical_name")))
    parts.append(row("Website", esc(f["domain"]), "sheet, checked live"))
    addr = latest_claim(claims, "address")
    if addr and addr["evidence"]:
        parts.append(row("Address", esc(addr["evidence"].replace("Google Business Profile: ", "")), addr["source"]))
    parts.append(row("Phone", esc(f["phone_e164"]), ", ".join(sorted({c["source"] for c in claims if c["attr"] == "phone_e164"}))))
    parts.append(row("Practice", esc(f["primary_practice"]) + (" · " + ", ".join(f["practice_areas"]) if f["practice_areas"] else ""), source_of("primary_practice")))
    parts.append(row("Fee model", esc(f["fee_model"] or "not stated on the site — never guessed"), source_of("fee_model")))
    parts.append(row("Attorneys", esc(f["attorney_count"] or "not stated"), source_of("attorney_count")))
    parts.append(row("Tier", esc(f["tier"]), "reconcile"))
    parts.append(row("Case system", esc(f["cms_detected"] or "none detected"), source_of("cms_detected")))
    parts.append(row("Google rating", f"{esc(listing_v.get('rating'))} from {esc(listing_v.get('review_count'))} reviews" if listing_v else "no listing", "Google Business Profile via Serper"))
    hc = latest_claim(claims, "vendor_headcount_range")
    if hc:
        parts.append(row("Headcount on the sheet", esc(hc["value"]), hc["source"]))
    parts.append("</table>")

    parts.append("<h3>The site</h3><table class='grid'><tr><th>Page</th><th>URL</th><th>Answer</th><th>Words</th></tr>")
    for p in d["pages"]:
        parts.append(f"<tr><td>{esc(p['page_kind'])}</td><td class='q'>{esc(p['url'])}</td>"
                     f"<td>{esc(p['status_code'])}</td><td>{esc(p['word_count'] or '')}</td></tr>")
    parts.append("</table>")
    if gaps_v:
        parts.append("<p><strong>What the site lacks:</strong> " + "; ".join(
            f"{esc(g['gap'].replace('_', ' '))} ({esc(g['evidence'])})" for g in gaps_v) + ".</p>")
    shows = [c for c in claims if c["source"] == "site:page" and c["attr"] in
             ("online_intake_form", "social_links", "copyright_year", "site_emails", "staff_listed")]
    if shows:
        parts.append("<p><strong>What the site shows:</strong> " + "; ".join(
            f"{esc(c['attr'].replace('_', ' '))}: {esc(json.dumps(c['value']) if not isinstance(c['value'], str) else c['value'])}"
            for c in shows) + ".</p>")

    parts.append("<h3>The people</h3><table class='grid'><tr><th>Name</th><th>Role · title</th><th>Where from</th><th>LinkedIn</th><th>Addresses</th></tr>")
    for c in d["contacts"]:
        ems = [e for e in d["emails"] if e["contact_id"] == c["id"]]
        em = "<br>".join(f"{esc(e['email'])} <span class='tag'>{esc(e['status'])}</span>" for e in ems) or "—"
        parts.append(f"<tr><td>{esc(c['full_name'])}</td><td>{esc(c['role'])} · {esc(c['title'] or '')}</td>"
                     f"<td>{esc(c['source'])}</td><td class='q'>{esc(c['linkedin_url'] or '')}</td><td>{em}</td></tr>")
    parts.append("</table>")
    lc = latest_claim(claims, "linkedin_company_url")
    if lc:
        parts.append(f"<p><strong>Company page:</strong> <span class='q'>{esc(lc['value'])}</span> ({esc(lc['source'])})</p>")

    if listing_v:
        parts.append("<h3>The Google Business Profile</h3><table class='kv'>")
        for k in ("name", "category", "address", "phone", "website", "rating", "review_count", "url"):
            if listing_v.get(k) is not None:
                parts.append(row(k.replace("_", " "), esc(listing_v[k]), "listing:serper"))
        parts.append("</table>")
    parts.append("</section>")

    # 5 · reviews
    parts.append(f"<section><h2>5 · The reviews, word for word ({len(reviews)})</h2>"
                 "<p class='note'>The poorest reviews are fetched first, because they are the ones that name a pain; the rest fill the cap of twenty.</p>")
    for r in sorted(reviews, key=lambda r: (r.get("rating") or 9, r.get("date") or "")):
        stars = "★" * int(r.get("rating") or 0) + "☆" * (5 - int(r.get("rating") or 0))
        parts.append(f"<div class='review'><div class='rh'><span class='stars'>{stars}</span> "
                     f"<span>{esc(r.get('author'))}</span> <span class='dt'>{esc(r.get('date'))}</span></div>"
                     f"<div class='rt'>{esc(r.get('text'))}</div></div>")
    parts.append("</section>")

    # 6 · pain analysis
    parts.append("<section><h2>6 · What hurts — the AI pain analysis</h2>")
    if pain_v:
        parts.append(f"<p class='summary'>{esc(pain_v.get('summary'))}</p>")
        for p in pains:
            parts.append(f"<div class='pain'><div class='ph'>{esc(p['headline'])} <span class='tag'>{esc(p['kind'])} · {int(float(p.get('confidence', 0)) * 100)}%</span></div>"
                         f"<div class='pq'>“{esc(p['quote'])}” <span class='src'>— from {esc(p['source'])}</span></div>"
                         f"<div class='pw'>{esc(p['why_it_matters'])}</div></div>")
        dropped = pain_v.get("dropped") or []
        if dropped:
            parts.append("<p class='note'>Thrown away for lack of a quote: " + "; ".join(esc(x[0]) for x in dropped) + ".</p>")
        parts.append(f"<p class='note'>Read: {esc(', '.join(pain_v.get('read', [])))}. Model: {esc(pain['source'])}.</p>")
    else:
        parts.append("<p>No pain analysis yet.</p>")
    parts.append("</section>")

    # 7 · where it stopped
    parts.append("<section><h2>7 · Where the engine stopped, and why</h2><ul>")
    if lead:
        parts.append(f"<li>Lead state <strong>{esc(lead['state'])}</strong>, band <strong>{esc(lead['band'])}</strong>, fit {esc(lead['fit_score'])}, intent {esc(lead['intent_score'])}.</li>")
    if f["fee_model"] in (None, "unknown"):
        parts.append("<li>The site never states a fee model and the engine never guesses one, so the lead is held before outreach. A rule for practices whose sites never state fees (immigration, family) is the decision this report asks for.</li>")
    if len({c["full_name"].split()[0].lower() for c in d["contacts"]}) < len(d["contacts"]):
        parts.append("<li>The sheet's short name and the site's full name became two people; they should merge into one.</li>")
    if not d["verify"]:
        parts.append("<li>No address was verified: verification runs only once the firm is classified, so no credit was spent on a lead that could not yet become ready.</li>")
    parts.append("</ul></section>")

    # 8 · cost
    parts.append(f"""<section><h2>8 · What this firm cost</h2><table class='kv'>
{row('Serper', f'{serper} credits ({listing_calls} for the listing and its reviews)', 'search_log')}
{row('NeverBounce', f'{len(d["verify"])} checks, ${nb_cost:.3f}', 'verify_attempt')}
{row('AI (OpenRouter)', f'{len(d["ai"])} readings, ${ai_cost:.3f}', 'llm_call')}
</table></section>""")

    # 9 · journey
    parts.append("<section class='journey'><h2>9 · The email journey the engine would send</h2>")
    for a in journey.get("assumptions", []):
        parts.append(f"<p class='note'>{esc(a)}</p>")
    if journey.get("excluded"):
        parts.append(f"<p><strong>Not rendered:</strong> {esc(journey['excluded'])}</p>")
    parts.append("<p class='note'>Each email is the conversation (the copy), then Legal Soft's offer in its "
                 "own published numbers, chosen for this lead's pain and different in every email, then "
                 "one call to action. The button is how a sending tool shows the same link.</p>")
    sig = journey.get("signature")
    for t in journey.get("touches", []):
        reply = t["cta"].split("\n", 1)[1] if "\n" in (t.get("cta") or "") else ""
        parts.append(
            f"<div class='email'><div class='eh'><span class='day'>Day {t['day'] + 1}</span> · Email {t['step']}</div>"
            f"<div class='es'>Subject: {esc(t['subject'])}</div>"
            f"<pre class='eb'>{esc(t.get('copy') or t['body'])}</pre>"
            + (f"<div class='usp'><span class='lbl'>The offer</span>{esc(t['usp'])}</div>" if t.get("usp") else "")
            + (f"<div class='cta'>{cta_html()}<div class='ctal'>{esc(t['cta'].splitlines()[0])}</div>"
               f"<div class='ctar'>{esc(reply)}</div></div>" if t.get("cta") else "")
            + (f"<pre class='sig'>{esc(sig)}</pre>" if sig else "")
            + "</div>"
        )
    if journey.get("sender_missing"):
        parts.append("<p class='note'>Still blank in the sender settings before anything can be sent: " + esc(", ".join(journey["sender_missing"])) + ".</p>")
    parts.append("</section>")

    body = "\n".join(parts)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(f['canonical_name'])} — enrichment report</title>
<style>
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1b1f24; font-size: 10.5pt; line-height: 1.45; }}
.cover {{ border-bottom: 3px solid #0b3d91; padding-bottom: 10px; margin-bottom: 18px; }}
.kicker {{ color: #0b3d91; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; font-size: 9pt; margin: 0; }}
h1 {{ font-size: 26pt; margin: 4px 0 2px; }} .sub {{ margin: 0; color: #4a5568; font-size: 12pt; }} .meta {{ color: #4a5568; }}
h2 {{ font-size: 15pt; color: #0b3d91; border-bottom: 1px solid #cbd5e0; padding-bottom: 3px; margin: 22px 0 8px; page-break-after: avoid; }}
h3 {{ font-size: 11.5pt; margin: 14px 0 6px; }}
section {{ page-break-inside: auto; }}
table {{ border-collapse: collapse; width: 100%; margin: 4px 0 10px; }}
th, td {{ text-align: left; vertical-align: top; padding: 4px 6px; border-bottom: 1px solid #e2e8f0; font-size: 9.5pt; }}
table.kv th {{ width: 24%; color: #4a5568; font-weight: 600; }} table.kv td.src, .src {{ color: #718096; font-size: 8.5pt; }}
table.grid th {{ background: #f1f5fb; }}
.q {{ font-family: Consolas, monospace; font-size: 8.5pt; word-break: break-all; }}
.glance {{ display: flex; gap: 10px; margin: 8px 0; }} .glance div {{ flex: 1; background: #f1f5fb; border-radius: 6px; padding: 8px; text-align: center; }}
.glance .n {{ display: block; font-size: 18pt; font-weight: 700; color: #0b3d91; }} .glance .l {{ font-size: 8.5pt; color: #4a5568; }}
.verdict {{ font-size: 11pt; }}
.review {{ border-left: 3px solid #cbd5e0; padding: 4px 8px; margin: 6px 0; page-break-inside: avoid; }}
.review .rh {{ font-size: 9pt; color: #4a5568; }} .stars {{ color: #d69e2e; letter-spacing: 1px; }} .dt {{ color: #718096; }} .rt {{ margin-top: 2px; }}
.pain {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px; margin: 8px 0; page-break-inside: avoid; }}
.ph {{ font-weight: 700; font-size: 11pt; }} .pq {{ font-family: Georgia, serif; font-style: italic; margin: 4px 0; background: #fffbea; padding: 3px 6px; }}
.pw {{ color: #4a5568; }} .summary {{ font-family: Georgia, serif; font-size: 11pt; }}
.tag {{ background: #edf2f7; border-radius: 4px; padding: 1px 5px; font-size: 8pt; color: #4a5568; }}
.note {{ color: #718096; font-size: 9pt; }}
.email {{ border: 1px solid #cbd5e0; border-radius: 6px; padding: 8px 12px; margin: 10px 0; page-break-inside: avoid; }}
.eh {{ font-size: 9pt; color: #0b3d91; font-weight: 600; }} .day {{ background: #0b3d91; color: #fff; border-radius: 4px; padding: 1px 6px; }}
.es {{ font-weight: 700; margin: 4px 0; }} .eb {{ font-family: Georgia, serif; font-size: 10.5pt; white-space: pre-wrap; margin: 0; }}
.usp {{ font-family: Georgia, serif; font-size: 10.5pt; background: #eef4ff; border-left: 3px solid #0b3d91; padding: 6px 10px; margin: 8px 0; }}
.usp .lbl {{ display: block; font-family: "Segoe UI", Arial, sans-serif; font-size: 8pt; font-weight: 700; color: #0b3d91; text-transform: uppercase; letter-spacing: .06em; }}
.cta {{ margin: 8px 0; }} .ctal {{ font-family: Consolas, monospace; font-size: 8.5pt; color: #4a5568; margin-top: 4px; }} .ctar {{ font-family: Georgia, serif; font-size: 10pt; }}
.sig {{ font-family: Georgia, serif; font-size: 9pt; color: #4a5568; white-space: pre-wrap; margin: 6px 0 0; border-top: 1px solid #e2e8f0; padding-top: 4px; }}
</style></head><body>{body}</body></html>"""


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    chrome = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)
    if not chrome:
        print("Chrome not found; HTML only")
        return False
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()]
    subprocess.run(cmd, check=False, timeout=120, capture_output=True)
    return pdf_path.is_file()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("firm_id")
    ap.add_argument("--subject", default=None, help="subject for email 1")
    ap.add_argument("--assume-fee", default=None, help="fee model to render the journey with")
    ap.add_argument("--out", default=str(PROJECT_ROOT / ".local" / "reports"))
    args = ap.parse_args()
    with lge_db.connect() as conn:
        d = collect(conn, args.firm_id)
    journey = render_journey(d, args.subject, args.assume_fee)
    page = build_html(d, journey, args.subject)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in d["firm"]["canonical_name"].lower()).strip("-")
    html_path = out / f"{slug}.html"
    pdf_path = out / f"{slug}.pdf"
    html_path.write_text(page, encoding="utf-8")
    ok = to_pdf(html_path, pdf_path)
    print("html:", html_path)
    print("pdf:", pdf_path if ok else "(not produced)")
    print("touches rendered:", len(journey.get("touches", [])), "| excluded:", journey.get("excluded"))


if __name__ == "__main__":
    main()
