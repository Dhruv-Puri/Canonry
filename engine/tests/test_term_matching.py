"""Banned terms match whole phrases, not stray digits.

Found 3 Nov 2026 by the browser run: the term "5,000+ teams" was split at its comma into "5" and
"000+ teams", and terms matched anywhere inside other words or numbers. So "Setup takes 5
minutes", "Pulse 2.5" and "Rs 1,599" each got a Must fix "banned term", and "#10" was flagged
as the banned "#1".

Run:  .venv/Scripts/python engine/tests/test_term_matching.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_term_matching")

import checkers  # noqa: E402
from seed import seed  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


expect(checkers.term_variants("5,000+ teams") == ["5,000+ teams"], "a comma inside a number does not split a phrase")
expect(checkers.term_variants("Quillmark Insights, staff,employees") == ["Quillmark Insights", "staff", "employees"],
       "commas between phrases still split them")

ws = seed()
conn = _db.connect()


class Ctx:
    pass


ctx = Ctx()
ctx.conn, ctx.ws, ctx.kv, ctx.revision_id = conn, ws, 0, "t"
ctx.rule = lambda key: None


def flagged(text):
    return [f["span"]["text"] for f in checkers.check_terminology(ctx, text)]


for text in ("Setup takes 5 minutes.", "Pulse 2.5 is here.", "Plans from ₹1,599.", "We are #10 on the list.",
             "Trusted by 25,000+ teams."):
    hits = [h for h in flagged(text) if h.lower() != "trusted by"]
    expect(not hits, f"ordinary copy is not a banned term: {text!r} ({hits})")
expect("5,000+ teams" in flagged("Trusted by 5,000+ teams."), "the retired figure is still caught whole")
expect("#1" in flagged("We are #1."), '"#1" is still caught')
expect("Quillmark Insights" in flagged("Meet Quillmark Insights 2.0."), "retired names are still caught")
conn.close()

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("TERMS MATCH WHOLE PHRASES")
