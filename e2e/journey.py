"""End-to-end walk of Canonry in a real browser, the way a judge uses it.

Not part of CI: it needs a running engine and web app. Typical local run
(Windows, Git Bash; macOS/Linux use .venv/bin/python):

    sh e2e/start_engine.sh fresh                                   # engine on :8202, temp DB, no AI keys
    cd web && CANONRY_ENGINE_URL=http://127.0.0.1:8202 npx next dev -p 3202
    .venv/Scripts/python e2e/journey.py                            # every phase except "offline"
    # stop the engine, keep the web app running, then:
    .venv/Scripts/python e2e/journey.py offline

Phases (default: journey reliability layout):
  journey      creator -> findings -> accept/edit/dispute -> submit -> reviewer approve / request
               changes / override -> signed proof -> public verify (text and file); agency
               isolation; admin knowledge-base edit and its effect on a re-check; insights
  reliability  hostile text, wrong/corrupt/0-byte files, double clicks, refresh and back,
               two tabs, signed-out session, unknown ids
  layout       every screen at 1280 px and 390 px: horizontal overflow, small tap targets,
               unlabeled inputs, images without alt; screenshots to look at
  offline      the engine is stopped: every page must say so in plain words, never go blank

Needs Playwright and Microsoft Edge (channel "msedge"). Screenshots and a
summary go to --out (default e2e/.tmp/shots). Exit code 1 if any check fails.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PWTimeout, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"

results: list[tuple[bool, str]] = []
OUT = Path()
BASE = ""


def check(cond: bool, msg: str) -> bool:
    results.append((bool(cond), msg))
    print(("ok:   " if cond else "FAIL: ") + msg, flush=True)
    return bool(cond)


def shot(page: Page, name: str, full: bool = True) -> None:
    try:
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    except Exception as e:  # a screenshot must never stop the walk
        print(f"      (screenshot {name} failed: {e})")


# ---- helpers --------------------------------------------------------------------------

def watch(page: Page, label: str) -> list[str]:
    """Collect page crashes and server errors for one page."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"{label}: page error {e}"))
    page.on("response", lambda r: errors.append(f"{label}: {r.status} {r.url}")
            if r.status >= 500 and "/engine/" in r.url else None)
    return errors


def new_context(browser: Browser, width: int = 1280, height: int = 860) -> BrowserContext:
    ctx = browser.new_context(viewport={"width": width, "height": height}, base_url=BASE)
    ctx.set_default_timeout(30_000)
    return ctx


def guest(ctx: BrowserContext, role: str) -> Page:
    """Pick a role on the welcome screen and Continue as guest (sign-in is async)."""
    page = ctx.new_page()
    page.goto("/")
    page.get_by_role("button", name=re.compile("Continue as guest")).wait_for()
    label = {"creator": "Creator", "reviewer": "Reviewer", "agency": "Agency partner", "admin": "Brand admin"}[role]
    page.locator("label", has_text=label).first.click()
    page.get_by_role("button", name=re.compile("Continue as guest")).click()
    # the button turns into "Opening Canonry…" first; signed in once the app's main nav exists
    page.locator("nav[aria-label=Main]").first.wait_for(state="attached", timeout=60_000)
    page.wait_for_load_state("networkidle")
    # roles other than creator are redirected from / to their own home
    for _ in range(100):
        if not page.get_by_text("Opening your workspace").count():
            break
        page.wait_for_timeout(300)
    return page


BUSY = re.compile(r"^(Checking|Uploading|Opening Canonry|Signing in|Saving)…$")


def settle(page: Page) -> None:
    """Wait for the action in flight to finish: network quiet, no busy button, Re-check usable again."""
    page.wait_for_timeout(250)
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PWTimeout:
        pass
    busy = page.get_by_role("button", name=BUSY)
    recheck = page.get_by_role("button", name="Re-check")
    for _ in range(200):
        if not busy.count() and (not recheck.count() or recheck.first.is_enabled()):
            return
        page.wait_for_timeout(300)


def body_text(page: Page) -> str:
    return page.locator("body").inner_text()


def blank_or_crashed(page: Page) -> bool:
    t = body_text(page).strip()
    return len(t) < 20 or "Application error" in t or "Unhandled Runtime Error" in t


def submit_text(page: Page, title: str, content: str, double: bool = False) -> str:
    page.goto("/new")
    page.get_by_label("Title").fill(title)
    page.get_by_label("Content").fill(content)
    btn = page.get_by_role("button", name=re.compile("Submit for check"))
    btn.dblclick() if double else btn.click()
    page.wait_for_url(re.compile(r"/submissions/sub_"), timeout=120_000)
    settle(page)
    page.get_by_role("heading", name=re.compile("Findings")).wait_for()
    return page.url.rsplit("/", 1)[-1]


def open_findings(page: Page) -> int:
    m = re.search(r"Findings \((\d+) open\)", body_text(page))
    return int(m.group(1)) if m else -1


def engine_json(page: Page, path: str):
    return page.evaluate("async (p) => { const r = await fetch('/engine' + p); return [r.status, await r.json()]; }", path)


def wait_new_revision(page: Page, sid: str, before: int, timeout_s: int = 90) -> bool:
    """After a fix or dispute: poll the engine until the new revision exists and the page shows it."""
    end = time.time() + timeout_s
    while time.time() < end:
        _, d = engine_json(page, f"/submissions/{sid}")
        n = len(d.get("revisions", []))
        if n > before:
            # the page has reloaded the item once its revision picker shows the new revision
            page.get_by_text(f"Latest (rev {d['latest_revision']['revision_no']})").first.wait_for(state="attached", timeout=60_000)
            recheck = page.get_by_role("button", name="Re-check")
            for _ in range(100):
                if not recheck.count() or recheck.first.is_enabled():
                    break
                page.wait_for_timeout(300)
            return True
        if page.locator("main").get_by_role("alert").count():
            return False
        page.wait_for_timeout(400)
    return False


def resolve_all(page: Page, sid: str, edit_one: bool = False) -> None:
    """Settle every open finding through the UI: one-click fix, else (once) an own-words edit, else dispute."""
    edited = not edit_one
    for _ in range(25):
        _, d = engine_json(page, f"/submissions/{sid}")
        open_f = [f for f in d["findings"] if f["status"] == "open"]
        if not open_f:
            return
        f = open_f[0]
        card = page.locator(f"#finding-{f['id']}")
        card.wait_for()
        before = len(d["revisions"])
        fix = card.get_by_role("button", name=re.compile("^(Accept fix|Remove the flagged phrase)$"))
        if fix.count():
            fix.first.click()
        else:
            if card.locator("details:not([open]) > summary").count():
                card.locator("details > summary").first.click()
            own = card.get_by_label("Your replacement for the flagged phrase")
            if not edited and own.count():
                own.fill("an analytics platform")
                card.get_by_role("button", name="Apply my edit").click()
                edited = True
            else:
                card.get_by_label("Dispute reason").fill("E2E: rule does not apply here")
                card.get_by_role("button", name="Dispute").click()
        if not wait_new_revision(page, sid, before):
            alert = page.locator("main").get_by_role("alert")
            check(False, f"resolving {f['category']} made a new revision ({alert.first.inner_text()[:100] if alert.count() else 'timeout'})")
            return


RUN = time.strftime("%H%M%S")
LAUNCH = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully "
          "ISO 27001 certified. Plans start at just ₹999/month!")
CLEAN = "Quillmark Pulse helps teams read their data. Start your free trial at quillmark.co/pulse."


# ---- phase: journey -------------------------------------------------------------------

def phase_journey(browser: Browser) -> None:
    print("\n== journey: creator")
    cctx = new_context(browser)
    cp = guest(cctx, "creator")
    errs = watch(cp, "creator")
    shot(cp, "j01-creator-home")
    check("Launch post" in body_text(cp) or "submission" in body_text(cp).lower(), "creator home lists work")
    sid = submit_text(cp, f"E2E launch post {RUN}", LAUNCH, double=True)
    shot(cp, "j02-findings")
    n0 = open_findings(cp)
    check(n0 >= 4, f"the launch post has findings ({n0} open)")
    status, d = engine_json(cp, f"/submissions/{sid}")
    check(len(d["revisions"]) == 1, f"double-clicking Submit for check made one revision ({len(d['revisions'])})")
    _, subs = engine_json(cp, "/submissions")
    dup = [s for s in subs["submissions"] if s["title"] == f"E2E launch post {RUN}"]
    check(len(dup) == 1, f"double-clicking Submit for check made one submission ({len(dup)})")

    # accept one fix with a double click, then the rest one by one
    accept = cp.get_by_role("button", name="Accept fix").first
    accept.dblclick()
    settle(cp)
    _, d = engine_json(cp, f"/submissions/{sid}")
    check(len(d["revisions"]) == 2, f"double-clicking Accept fix made one new revision ({len(d['revisions'])})")
    check(not cp.get_by_text("changed since you opened it").count(), "no stale-tab warning after a double click")
    resolve_all(cp, sid, edit_one=True)
    shot(cp, "j03-all-resolved")
    check(open_findings(cp) == 0, f"every finding resolved ({open_findings(cp)} open)")
    cp.get_by_role("button", name="Compare with previous").click()
    check(cp.get_by_text(re.compile(r"Changes from rev \d+ to rev \d+")).count() > 0, "compare shows a word diff")
    shot(cp, "j04-compare")
    cp.get_by_role("button", name=re.compile("Viewing changes")).click()
    cp.get_by_role("button", name=re.compile("Submit for review")).dblclick()
    settle(cp)
    check("In review" in body_text(cp), "submitted for review")
    check(not cp.get_by_text("can't be changed").count(), "double-clicking Submit for review shows no error")
    shot(cp, "j05-in-review")

    print("\n== journey: reviewer requests changes, creator fixes, reviewer approves")
    rctx = new_context(browser)
    rp = guest(rctx, "reviewer")
    errs += watch(rp, "reviewer")
    shot(rp, "j06-review-queue")
    check(f"E2E launch post {RUN}" in body_text(rp), "the reviewer's queue shows the submitted item")
    rp.get_by_text(f"E2E launch post {RUN}").first.click()
    rp.wait_for_url(re.compile(sid))
    settle(rp)
    rp.get_by_label(re.compile("Reviewer comment")).fill("Please add the trial link")
    rp.get_by_role("button", name="Request changes").click()
    settle(rp)
    check("Changes requested" in body_text(rp), "reviewer requested changes")
    cp.reload()
    settle(cp)
    check("Changes requested" in body_text(cp) and "Please add the trial link" in body_text(cp),
          "the creator sees the request and the comment")
    cp.get_by_role("button", name=re.compile("Submit for review")).click()
    settle(cp)
    rp.reload()
    settle(rp)
    shot(rp, "j07-reviewer-decision")
    rp.get_by_role("button", name=re.compile("Approve")).dblclick()
    settle(rp)
    rp.get_by_text("Proof of Compliance signed").wait_for(timeout=30_000)
    _, d = engine_json(rp, f"/submissions/{sid}")
    check(len([a for a in d["approvals"] if a["action"] == "approve"]) == 1,
          "double-clicking Approve signed once")
    shot(rp, "j08-signed")
    poc = d["poc"]["id"]
    approved = d["latest_revision"]["content"]

    print("\n== journey: public verify (signed out)")
    pctx = new_context(browser)
    pp = pctx.new_page()
    errs += watch(pp, "verify")
    pp.goto(f"/verify/{poc}")
    pp.get_by_text("Genuine seal").wait_for()
    pp.get_by_label("Published text").fill(approved)
    pp.get_by_role("button", name="Check this text").click()
    pp.get_by_text("Verified: this is the approved content").wait_for()
    shot(pp, "j09-verify-ok")
    pp.get_by_label("Published text").fill(approved + " Now 50% off!")
    pp.get_by_role("button", name="Check this text").click()
    pp.get_by_text("Modified").first.wait_for()
    check(True, "verify says Verified for the approved text and Modified for a change")
    shot(pp, "j10-verify-modified")
    pp.goto("/verify/poc_does_not_exist")
    settle(pp)
    shot(pp, "j11-verify-unknown")
    check("Unknown" in body_text(pp), "an unknown proof id says Unknown")

    print("\n== journey: override on another item, file upload and file verify")
    sid2 = submit_text(cp, "E2E override", "Quillmark Pulse is India's #1 analytics platform.")
    cp.get_by_role("button", name=re.compile("Submit for review")).click()
    settle(cp)
    rp.goto(f"/submissions/{sid2}")
    settle(rp)
    if rp.get_by_label("Override reason").count():
        rp.get_by_label("Override reason").first.fill("E2E: approved by legal")
        rp.get_by_role("button", name="Override finding").first.click()
        settle(rp)
        check("override" in body_text(rp).lower(), "reviewer overrode a finding with a reason")
    shot(rp, "j12-override")

    cp.goto("/new")
    cp.get_by_role("tab", name=re.compile("PDF, Word or image")).click()
    cp.get_by_label("Title").fill(f"E2E social image {RUN}")
    cp.locator("input[type=file]").set_input_files(str(DEMO / "social_launch.png"))
    cp.get_by_label(re.compile("Alt text")).fill("Quillmark Pulse launch banner")
    cp.get_by_role("button", name=re.compile("Upload and check")).dblclick()
    cp.wait_for_url(re.compile(r"/submissions/sub_"), timeout=120_000)
    settle(cp)
    shot(cp, "j13-image-findings")
    check(cp.locator("img[src^='/engine/assets/']").count() == 1, "the uploaded image is previewed")
    _, subs = engine_json(cp, "/submissions")
    check(len([s for s in subs["submissions"] if s["title"] == f"E2E social image {RUN}"]) == 1,
          "double-clicking Upload and check made one submission")

    cp.goto("/new")
    cp.get_by_role("tab", name=re.compile("PDF, Word or image")).click()
    cp.get_by_label("Title").fill("E2E brochure")
    cp.locator("input[type=file]").set_input_files(str(DEMO / "quillmark_brochure.docx"))
    cp.get_by_role("button", name=re.compile("Upload and check")).click()
    cp.wait_for_url(re.compile(r"/submissions/sub_"), timeout=120_000)
    settle(cp)
    shot(cp, "j14-docx-findings")
    sid3 = cp.url.rsplit("/", 1)[-1]
    resolve_all(cp, sid3)  # everything settled, so it can be approved and stamped
    cp.get_by_role("button", name=re.compile("Submit for review")).click()
    settle(cp)
    rp.goto(f"/submissions/{sid3}")
    settle(rp)
    rp.get_by_role("button", name=re.compile("Approve")).click()
    settle(rp)
    _, d3 = engine_json(rp, f"/submissions/{sid3}")
    ok = check(bool(d3.get("poc")), "the Word file was approved and stamped")
    if ok:
        with rp.expect_download() as dl:
            rp.get_by_role("link", name="Download stamped file").click()
        stamped = OUT / "stamped.docx"
        dl.value.save_as(str(stamped))
        pp.goto(f"/verify/{d3['poc']['id']}")
        pp.get_by_label("Published file").set_input_files(str(stamped))
        pp.get_by_role("button", name="Check this file").click()
        pp.get_by_text(re.compile("Matches the signed record|Does not verify")).wait_for()
        check("Matches the signed record" in body_text(pp), "the stamped Word file verifies on the public page")
        shot(pp, "j15-verify-file")
        pp.get_by_label("Published file").set_input_files(str(DEMO / "quillmark_pulse_onepager.pdf"))
        pp.get_by_role("button", name="Check this file").click()
        pp.get_by_text(re.compile("Matches the signed record|Does not verify")).wait_for()
        check("Does not verify" in body_text(pp), "a different file does not verify")

    print("\n== journey: agency partner sees only its own work")
    actx = new_context(browser)
    ap = guest(actx, "agency")
    errs += watch(ap, "agency")
    shot(ap, "j16-agency-empty")
    check(f"E2E launch post {RUN}" not in body_text(ap), "agency does not see the creator's work")
    asid = submit_text(ap, f"E2E agency post {RUN}", LAUNCH)
    ap.goto("/agency")
    settle(ap)
    check(f"E2E agency post {RUN}" in body_text(ap), "agency sees its own work")
    shot(ap, "j17-agency-list")
    ap.goto(f"/submissions/{sid}")
    settle(ap)
    shot(ap, "j18-agency-forbidden")
    check("Launch" not in body_text(ap) and not blank_or_crashed(ap),
          "agency opening another team's item gets a plain not-found message")
    _, ad = engine_json(ap, f"/submissions/{asid}")
    check(not any(c.get("confidential") for f in ad["findings"] for c in f["citations"]),
          "agency findings cite no confidential facts")

    print("\n== journey: brand admin edits the knowledge base; a re-check uses it")
    dctx = new_context(browser)
    dp = guest(dctx, "admin")
    errs += watch(dp, "admin")
    shot(dp, "j19-admin-home")
    dp.goto("/kb")
    settle(dp)
    shot(dp, "j20-kb")
    # Through the API the UI uses: ban a new word, then a creator's re-check flags it.
    word = f"e2eword{int(time.time()) % 100000}"
    st, res = dp.evaluate("""async (w) => {
        const r = await fetch('/engine/kb/terms', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({banned_or_check: w, preferred: 'plain words', note: 'e2e', severity: 'medium',
                                reason: 'E2E: banned for the test'})});
        return [r.status, await r.json()]; }""", word)
    check(st == 200, f"admin added a banned term ({st})")
    sid4 = submit_text(cp, "E2E kb effect", f"Quillmark Pulse is {word} for teams. Start at quillmark.co/pulse.")
    check(word in body_text(cp) and open_findings(cp) >= 1, "a new draft is flagged for the newly banned term")
    tid = res.get("entity", {}).get("id")
    st, rr = dp.evaluate("""async ([id, v]) => { const r = await fetch('/engine/kb/terms/' + id + '/retire',
        {method:'POST', headers:{'Content-Type':'application/json'},
         body: JSON.stringify({reason: 'E2E: done', expected_version: v})}); return [r.status, await r.json()]; }""",
        [tid, res.get("entity", {}).get("version")])
    check(st == 200, f"admin retired the term ({st} {str(rr)[:120]})")
    cp.get_by_role("button", name="Re-check").click()
    settle(cp)
    status, d4 = engine_json(cp, f"/submissions/{sid4}")
    flagged = [f for f in d4["findings"] if word in (f.get("span_text") or "")]
    check(not flagged, "after the admin retires the term, Re-check no longer flags it")
    dp.goto("/insights")
    settle(dp)
    shot(dp, "j21-insights")
    check(not blank_or_crashed(dp), "insights render")

    check(not errs, "no page crashes or engine 5xx during the journey" + (f": {errs[:4]}" if errs else ""))
    for c in (cctx, rctx, pctx, actx, dctx):
        c.close()


# ---- phase: reliability ---------------------------------------------------------------

def phase_reliability(browser: Browser) -> None:
    print("\n== reliability: hostile text")
    ctx = new_context(browser)
    page = guest(ctx, "creator")
    errs = watch(page, "reliability")
    page.goto("/new")
    page.get_by_label("Content").fill("   \n  ")
    check(page.get_by_role("button", name=re.compile("Submit for check")).is_disabled(),
          "whitespace-only content cannot be submitted")
    page.get_by_label("Content").fill("hello")
    page.get_by_label("Title").fill("   ")
    check(page.get_by_role("button", name=re.compile("Submit for check")).is_disabled(),
          "a blank title cannot be submitted")
    page.get_by_label("Title").fill("x")
    page.get_by_label("Content").fill("x" * 120_000)
    page.get_by_role("button", name=re.compile("Submit for check")).click()
    page.locator("main").get_by_role("alert").wait_for()
    check("too long" in page.locator("main").get_by_role("alert").inner_text(), "a 120,000-character draft is refused in plain words")
    shot(page, "r01-too-long", full=False)
    page.get_by_label("Content").fill("")
    for name, text in [("emoji", "🚀🔥 Quillmark Pulse 2.0 is #1 💯"),
                       ("hindi", "क्विलमार्क पल्स भारत का नंबर 1 एनालिटिक्स प्लेटफॉर्म है। ₹999/माह"),
                       ("rtl", "منصة Quillmark Pulse الأفضل في الهند"),
                       ("html", "<script>window.__xss=1</script><img src=x onerror=\"window.__xss=2\"> Quillmark Pulse #1"),
                       ("long", "Quillmark Pulse is India's #1 analytics platform. " * 1000)]:
        submit_text(page, f"E2E {name} " + "T" * (300 if name == "long" else 0), text)
        check(page.evaluate("window.__xss") is None, f"{name}: no script ran")
        check(not blank_or_crashed(page), f"{name}: the detail page renders")
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        check(scroll_w <= 1280, f"{name}: no sideways scroll ({scroll_w}px)")
        shot(page, f"r02-{name}", full=name != "long")

    print("\n== reliability: files")
    raw_png = (DEMO / "social_launch.png").read_bytes()
    raw_pdf = (DEMO / "quillmark_pulse_onepager.pdf").read_bytes()
    raw_docx = (DEMO / "quillmark_brochure.docx").read_bytes()
    bad = [("empty.pdf", b"", "application/pdf"), ("notes.txt", b"hello", "text/plain"),
           ("photo.pdf", raw_png, "application/pdf"), ("doc.png", raw_pdf, "image/png"),
           ("cut.pdf", raw_pdf[:600], "application/pdf"), ("cut.docx", raw_docx[:900], "application/octet-stream"),
           ("cut.png", raw_png[:300], "image/png"), ("big.pdf", b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024), "application/pdf")]
    for name, data, mime in bad:
        page.goto("/new")
        page.get_by_role("tab", name=re.compile("PDF, Word or image")).click()
        page.get_by_label("Title").fill(f"E2E bad {name}")
        page.locator("input[type=file]").set_input_files(files=[{"name": name, "mimeType": mime, "buffer": data}])
        page.get_by_role("button", name=re.compile("Upload and check")).click()
        try:
            page.locator("main").get_by_role("alert").wait_for(timeout=60_000)
            msg = page.locator("main").get_by_role("alert").inner_text()
        except PWTimeout:
            msg = ""
        check(bool(msg) and "/new" in page.url and not re.search(r"Engine error|Unexpected token|JSON", msg),
              f"{name}: refused in plain words ({msg[:90]!r})")
    shot(page, "r03-bad-file")

    print("\n== reliability: unknown ids")
    for path in ["/submissions/sub_nope", "/submissions/%3Cscript%3E", "/verify/nope", "/kb/nope", "/nope"]:
        page.goto(path)
        settle(page)
        t = body_text(page)
        check(not blank_or_crashed(page) and "Engine error" not in t, f"{path}: a plain message ({t.strip()[:70]!r})")
        shot(page, "r04-" + re.sub(r"\W+", "_", path))

    print("\n== reliability: refresh and back mid-flow")
    sid = submit_text(page, "E2E refresh", LAUNCH)
    page.reload()
    settle(page)
    check(open_findings(page) >= 4, "refresh on the findings page keeps the findings")
    page.go_back()
    settle(page)
    check(not blank_or_crashed(page), "back from the findings page renders")
    page.go_forward()
    settle(page)
    check(open_findings(page) >= 4, "forward again shows the findings")

    print("\n== reliability: two tabs on one draft")
    tab2 = ctx.new_page()
    errs += watch(tab2, "tab2")
    tab2.goto(f"/submissions/{sid}")
    settle(tab2)
    page.get_by_role("button", name="Accept fix").first.click()
    settle(page)
    tab2.get_by_role("button", name="Accept fix").nth(1).click()
    settle(tab2)
    shot(tab2, "r05-stale-tab")
    t2 = body_text(tab2)
    check("changed since you opened it" in t2 or "Reload" in t2, "the old tab is told the draft changed")
    status, d = engine_json(page, f"/submissions/{sid}")
    check(len(d["revisions"]) == 2, f"the old tab did not fork the history ({len(d['revisions'])} revisions)")
    tab2.close()

    print("\n== reliability: signed out mid-flow")
    ctx.clear_cookies()
    page.get_by_role("button", name="Re-check").click()
    try:
        page.get_by_role("button", name=re.compile("Continue as guest")).wait_for(timeout=20_000)
        check(True, "an expired session returns to the welcome screen")
    except PWTimeout:
        check(False, "an expired session returns to the welcome screen")
    shot(page, "r06-signed-out")
    check(not errs, "no page crashes or engine 5xx" + (f": {errs[:4]}" if errs else ""))
    ctx.close()


# ---- phase: layout --------------------------------------------------------------------

LAYOUT_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const out = {overflow: document.documentElement.scrollWidth - vw, wide: [], small: [], unlabeled: [], noalt: []};
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.right > vw + 1 && getComputedStyle(el).position !== 'fixed') {
      let p = el.parentElement, clipped = false;
      while (p) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { clipped = true; break; } p = p.parentElement; }
      if (!clipped) out.wide.push((el.tagName + '.' + (el.className.baseVal ?? el.className)).slice(0, 80));
    }
  }
  for (const el of document.querySelectorAll('button, a[href], select, input:not([type=hidden]), summary')) {
    const r = el.getBoundingClientRect();
    if (!r.width || getComputedStyle(el).visibility === 'hidden') continue;
    if (el.classList.contains('sr-only')) continue;
    if (r.height < 24 || r.width < 24) out.small.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40) + ` ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=radio]), textarea, select')) {
    const id = el.id; const named = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.closest('label') || (id && document.querySelector(`label[for="${id}"]`));
    if (!named) out.unlabeled.push((el.getAttribute('placeholder') || el.name || el.tagName).slice(0, 50));
  }
  for (const img of document.querySelectorAll('img')) if (!img.hasAttribute('alt')) out.noalt.push(img.src.slice(-40));
  out.wide = [...new Set(out.wide)].slice(0, 5); out.small = [...new Set(out.small)].slice(0, 8);
  return out;
}"""


def phase_layout(browser: Browser) -> None:
    print("\n== layout")
    for role, paths in [("creator", ["/", "/new", "SUB", "/insights"]),
                        ("reviewer", ["/review", "SUB", "/kb", "/insights"]),
                        ("agency", ["/agency", "/new"]),
                        ("admin", ["/admin", "/kb", "/admin/api"])]:
        for width, height in [(1280, 860), (390, 844)]:
            ctx = new_context(browser, width, height)
            page = guest(ctx, role)
            errs = watch(page, f"{role}@{width}")
            for path in paths:
                if path == "SUB":
                    _, subs = engine_json(page, "/submissions")
                    items = subs.get("submissions", [])
                    pick = next((s for s in items if s.get("open_findings")), items[0] if items else None)
                    if not pick:
                        continue
                    path = f"/submissions/{pick['id']}"
                page.goto(path)
                settle(page)
                name = f"l-{role}-{width}-{re.sub(r'[^a-z0-9]+', '_', path.lower()).strip('_') or 'home'}"
                shot(page, name)
                info = page.evaluate(LAYOUT_JS)
                check(info["overflow"] <= 0 and not info["wide"],
                      f"{name}: no sideways overflow ({info['overflow']}px {info['wide']})")
                check(not info["unlabeled"], f"{name}: every input has a label {info['unlabeled']}")
                check(not info["noalt"], f"{name}: every image has alt text {info['noalt']}")
                if info["small"]:
                    print(f"      note: small tap targets on {name}: {info['small']}")
                check(not blank_or_crashed(page), f"{name}: renders")
            check(not errs, f"{role}@{width}: no crashes or 5xx" + (f": {errs[:3]}" if errs else ""))
            ctx.close()
    # signed-out entry and a public verify page on a phone
    ctx = new_context(browser, 390, 844)
    page = ctx.new_page()
    page.goto("/")
    page.get_by_role("button", name=re.compile("Continue as guest")).wait_for()
    shot(page, "l-welcome-390")
    info = page.evaluate(LAYOUT_JS)
    check(info["overflow"] <= 0, f"welcome@390: no sideways overflow ({info['overflow']}px)")
    focused = None
    for _ in range(4):  # in `next dev` the dev-tools button takes the first Tab
        page.keyboard.press("Tab")
        focused = page.evaluate("document.activeElement && document.activeElement.tagName")
        if focused != "NEXTJS-PORTAL":
            break
    check(focused in ("INPUT", "BUTTON", "A"), f"welcome: keyboard Tab reaches a control ({focused})")
    ctx.close()


# ---- phase: offline -------------------------------------------------------------------

def phase_offline(browser: Browser) -> None:
    """Run with the engine stopped (web app still up)."""
    print("\n== offline: engine unavailable")
    ctx = new_context(browser)
    page = ctx.new_page()
    errs = watch(page, "offline")
    for path in ["/", "/new", "/review", "/kb", "/insights", "/admin", "/agency", "/submissions/sub_x",
                 "/verify/poc_x"]:
        page.goto(path)
        settle(page)
        page.wait_for_timeout(1500)
        t = body_text(page).strip()
        name = "o-" + (re.sub(r"[^a-z0-9]+", "_", path).strip("_") or "home")
        shot(page, name)
        plain = bool(re.search(r"can.t be reached|can.t reach|unavailable|try again", t, re.I))
        raw = bool(re.search(r"Unexpected token|Internal Server Error|Engine error|is not valid JSON|Failed to fetch", t))
        check(plain and not raw and not blank_or_crashed(page), f"{path}: plain 'unavailable' message ({t[:80]!r})")
    page_errors = [e for e in errs if "page error" in e]
    check(not page_errors, "no page crashes while the engine is down" + (f": {page_errors[:3]}" if page_errors else ""))
    ctx.close()


def main() -> int:
    global OUT, BASE
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phases", nargs="*", default=["journey", "reliability", "layout"])
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "http://localhost:3202"))
    ap.add_argument("--out", default=str(Path(__file__).parent / ".tmp" / "shots"))
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    OUT, BASE = Path(args.out), args.base.rstrip("/")
    OUT.mkdir(parents=True, exist_ok=True)
    phases = {"journey": phase_journey, "reliability": phase_reliability, "layout": phase_layout,
              "offline": phase_offline}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not args.headed)
        try:
            for name in args.phases:
                try:
                    phases[name](browser)
                except Exception as e:  # report, keep a picture of every open page, go on
                    check(False, f"phase {name} stopped: {type(e).__name__}: {' '.join(str(e).split())[:300]}")
                    for i, c in enumerate(browser.contexts):
                        for j, pg in enumerate(c.pages):
                            shot(pg, f"zz-{name}-stopped-{i}-{j}")
                            c.close()
                            break
        finally:
            browser.close()
    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; screenshots in {OUT}")
    for m in failed:
        print("  FAIL", m)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
