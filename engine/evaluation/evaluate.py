"""Evaluation harness (plan Section 9.6 targets, Appendix B protocol).

Runs every labelled sample in `eval_set.jsonl` through the real check pipeline
on a fresh database, matches the findings it kept against the planted issues,
and reports precision / recall / F1 overall, per checker, per tier and for the
claim checkers alone; plus the share of shown findings whose citation no longer
validates (the "0 hallucinated citations" guarantee).

Appendix B safeguards kept here:
- the set is split into `dev` (used while tuning) and a `frozen` held-out split
  (~30%); headline numbers come from `frozen` only;
- every run is recorded in `eval_runs` (scores + set version + git sha), so
  results are reproducible and comparable release to release;
- `--check` compares a fresh run with the committed baseline and fails on a
  regression, so CI can gate on it.

Run:
    .venv/Scripts/python engine/evaluation/evaluate.py                 # all splits, report
    .venv/Scripts/python engine/evaluation/evaluate.py --split frozen  # headline numbers
    .venv/Scripts/python engine/evaluation/evaluate.py --write-baseline
    .venv/Scripts/python engine/evaluation/evaluate.py --check         # CI gate
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package

# Print report symbols (≥, arrows) on any console encoding, e.g. cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# the evaluation measures the deterministic engine and must never spend a real AI key
os.environ["CANONRY_ENV_FILE"] = ""
for _key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_URL"):
    os.environ.pop(_key, None)

import db as _db  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SET_PATH = os.path.join(HERE, "eval_set.jsonl")
BASELINE_PATH = os.path.join(HERE, "eval_baseline.json")

_db.DB_PATH = os.environ.get("CANONRY_EVAL_DB") or os.path.join(HERE, "..", "..", "db", "canonry_eval.db")
for _suffix in ("", "-wal", "-shm"):
    _p = _db.DB_PATH + _suffix
    if os.path.exists(_p):
        os.remove(_p)

from db import _now, connect, gen_id, init_schema  # noqa: E402
from seed import seed  # noqa: E402

import claims  # noqa: E402
import pipeline  # noqa: E402

SET_VERSION = "eval@1"
CLAIM_CATEGORIES = {"contradicted_claim", "outdated_claim", "unsupported_claim"}
# a missed label belongs to the checker that was supposed to catch it
CATEGORY_CHECKER = {
    "banned_term": "terminology", "outdated_term": "terminology", "terminology": "terminology",
    "readability": "readability", "missing_cta": "readability", "missing_disclaimer": "readability",
    "tone": "tone", "confidential_leak": "confidential",
}
REGRESSION_TOLERANCE = 0.02      # a 2-point dip is noise; more is a regression
DEFINITE_TARGET = 0.95           # plan: ≥ 95% precision for "Definite" findings
CLAIM_RECALL_TARGET = 0.85       # plan: ≥ 85% recall on planted claim issues
CLAIM_PRECISION_TARGET = 0.80    # plan: ≥ 80% precision on planted claim issues


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, cwd=HERE).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def load_samples(split: str) -> List[Dict[str, Any]]:
    out = []
    with open(SET_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            if split == "all" or sample["split"] == split:
                out.append(sample)
    return out


def run_sample(conn, ws: str, sample: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Push one sample through the real pipeline exactly like a new submission."""
    sid, rid = gen_id("sub"), gen_id("rev")
    conn.execute(
        "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
        "VALUES (?,?,?,?,?,?,'Draft',?)",
        (sid, ws, f'eval {sample["id"]}: {sample["title"]}', sample["channel"],
         sample["source_type"], "arjun@quillmark", _now()),
    )
    conn.execute(
        "INSERT INTO revisions (id, submission_id, content, revision_no, created_at) VALUES (?,?,?,?,?)",
        (rid, sid, sample["content"], 1, _now()),
    )
    result = pipeline.run_check(conn, rid)
    return result["findings"]


def score_sample(conn, ws: str, sample: Dict[str, Any]) -> Dict[str, Any]:
    content = sample["content"]
    findings = run_sample(conn, ws, sample)
    labels = []
    for lab in sample.get("planted", []):
        pos = content.find(lab["text"])
        if pos < 0:
            raise SystemExit(f'eval set error: {sample["id"]} label {lab["text"]!r} is not in the content')
        labels.append({"label": lab, "start": pos, "end": pos + len(lab["text"]), "hit": False})

    matched: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    unmatched_findings = []
    for f in findings:
        fs, fe = f["span"]["start"], f["span"]["end"]
        hit = None
        for lab in labels:
            if lab["hit"]:
                continue
            if f["category"] == lab["label"]["category"] and fs < lab["end"] and lab["start"] < fe:
                lab["hit"] = True
                hit = lab
                break
        if hit:
            matched.append((f, hit["label"]))
        else:
            unmatched_findings.append(f)

    missed = [lab["label"] for lab in labels if not lab["hit"]]
    invalid_citations = 0
    for f in findings:
        probe = {"citations": f["citations"], "span": f["span"], "category": f["category"]}
        if not claims.citation_check(conn, ws, probe, content):
            invalid_citations += 1
    return {"sample": sample, "findings": findings, "matched": matched,
            "missed": missed, "extra": unmatched_findings,
            "invalid_citations": invalid_citations}


def prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn}


def evaluate(split: str, verbose: bool = False) -> Dict[str, Any]:
    init_schema()
    seed()
    conn = connect()
    ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
    samples = load_samples(split)
    results = [score_sample(conn, ws, s) for s in samples]

    totals = defaultdict(int)
    by_checker: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    by_category: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    tier_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0})
    claim_counts = {"tp": 0, "fp": 0, "fn": 0}
    invalid_citations = 0

    for r in results:
        invalid_citations += r["invalid_citations"]
        for f, lab in r["matched"]:
            totals["tp"] += 1
            by_checker[f["checker"]]["tp"] += 1
            by_category[f["category"]]["tp"] += 1
            tier_counts[f["tier"]]["tp"] += 1
            if f["category"] in CLAIM_CATEGORIES:
                claim_counts["tp"] += 1
        for f in r["extra"]:
            totals["fp"] += 1
            by_checker[f["checker"]]["fp"] += 1
            by_category[f["category"]]["fp"] += 1
            tier_counts[f["tier"]]["fp"] += 1
            if f["category"] in CLAIM_CATEGORIES:
                claim_counts["fp"] += 1
        for lab in r["missed"]:
            totals["fn"] += 1
            by_checker[lab.get("checker") or CATEGORY_CHECKER.get(lab["category"], "claims")]["fn"] += 1
            by_category[lab["category"]]["fn"] += 1
            if lab["category"] in CLAIM_CATEGORIES:
                claim_counts["fn"] += 1
        if verbose:
            print(f'  {r["sample"]["id"]:>4}  tp={len(r["matched"]):2}  '
                  f'fp={len(r["extra"]):2}  fn={len(r["missed"]):2}  '
                  f'{" | ".join(f["category"] + ":" + f["span"]["text"][:28] for f in r["extra"])}')
            for lab in r["missed"]:
                print(f'        MISSED {lab["category"]:<20} {lab["text"][:50]!r}')

    precision_by_tier = {}
    for tier, c in sorted(tier_counts.items()):
        precision_by_tier[tier] = round(c["tp"] / (c["tp"] + c["fp"]), 4) if c["tp"] + c["fp"] else None

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "set_version": SET_VERSION,
        "git": git_sha(),
        "split": split,
        "samples": len(samples),
        "overall": prf(totals["tp"], totals["fp"], totals["fn"]),
        "claims": prf(claim_counts["tp"], claim_counts["fp"], claim_counts["fn"]),
        "precision_by_tier": precision_by_tier,
        "by_checker": {k: prf(v["tp"], v["fp"], v["fn"]) for k, v in sorted(by_checker.items())},
        "by_category": {k: prf(v["tp"], v["fp"], v["fn"]) for k, v in sorted(by_category.items())},
        "invalid_citations": invalid_citations,
    }
    conn.execute(
        "INSERT INTO eval_runs (at, recall, precision_planted, precision_by_tier, invalid_citations, notes) "
        "VALUES (?,?,?,?,?,?)",
        (report["generated_at"], report["claims"]["recall"], report["claims"]["precision"],
         json.dumps(precision_by_tier), invalid_citations,
         f'split={split} set={SET_VERSION} git={report["git"]}'),
    )
    conn.commit()
    conn.close()
    return report


def print_report(report: Dict[str, Any]) -> None:
    o, c = report["overall"], report["claims"]
    print(f'\nEvaluation · split={report["split"]} · {report["samples"]} samples · {report["set_version"]}')
    print(f'  {"":<12}{"precision":>10}{"recall":>10}{"f1":>10}   (tp/fp/fn)')
    for name, m in (("overall", o), ("claims only", c)):
        print(f'  {name:<12}{m["precision"]:>10.3f}{m["recall"]:>10.3f}{m["f1"]:>10.3f}   '
              f'({m["tp"]}/{m["fp"]}/{m["fn"]})')
    print("  by checker:")
    for name, m in report["by_checker"].items():
        print(f'    {name:<12}{m["precision"]:>10.3f}{m["recall"]:>10.3f}{m["f1"]:>10.3f}   '
              f'({m["tp"]}/{m["fp"]}/{m["fn"]})')
    print("  precision by tier: " + " · ".join(
        f'{k}={"n/a" if v is None else format(v, ".3f")}' for k, v in report["precision_by_tier"].items()))
    print(f'  invalid citations shown: {report["invalid_citations"]}')

    targets = [(f"claims recall ≥ {CLAIM_RECALL_TARGET:.0%}", c["recall"], CLAIM_RECALL_TARGET),
               (f"claims precision ≥ {CLAIM_PRECISION_TARGET:.0%}", c["precision"], CLAIM_PRECISION_TARGET),
               (f'"definite" precision ≥ {DEFINITE_TARGET:.0%}',
                report["precision_by_tier"].get("definite") or 0.0, DEFINITE_TARGET)]
    print("  plan targets:")
    for label, value, target in targets:
        mark = "PASS" if value >= target else "FAIL"
        print(f'    [{mark}] {label} — now {value:.0%}')


def main() -> int:
    ap = argparse.ArgumentParser(description="Canonry evaluation harness (Appendix B)")
    ap.add_argument("--split", choices=["dev", "frozen", "all"], default="all")
    ap.add_argument("--verbose", action="store_true", help="per-sample matches, misses and extras")
    ap.add_argument("--write-baseline", action="store_true", help="record frozen numbers as the baseline")
    ap.add_argument("--check", action="store_true", help="exit 1 on regression, bad citations or a missed target")
    args = ap.parse_args()

    report = evaluate("frozen" if (args.check or args.write_baseline) else args.split, verbose=args.verbose)
    if not (args.check or args.write_baseline):
        print_report(report)

    if args.write_baseline:
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump({k: report[k] for k in ("generated_at", "set_version", "git", "split", "samples",
                                              "overall", "claims", "precision_by_tier", "by_checker",
                                              "by_category", "invalid_citations")}, fh, indent=2)
            fh.write("\n")
        print_report(report)
        print(f"\nbaseline written to {os.path.relpath(BASELINE_PATH, HERE)}")
        return 0

    if args.check:
        print_report(report)
        problems = []
        if report["invalid_citations"] != 0:
            problems.append(f'{report["invalid_citations"]} shown finding(s) have an invalid citation (must be 0)')
        definite = report["precision_by_tier"].get("definite")
        if definite is None or definite < DEFINITE_TARGET:
            problems.append(f'"definite" precision {definite} is below the {DEFINITE_TARGET:.0%} target')
        claims_m = report["claims"]
        if claims_m["recall"] < CLAIM_RECALL_TARGET:
            problems.append(f'claims recall {claims_m["recall"]:.0%} is below the {CLAIM_RECALL_TARGET:.0%} target')
        if claims_m["precision"] < CLAIM_PRECISION_TARGET:
            problems.append(f'claims precision {claims_m["precision"]:.0%} is below the {CLAIM_PRECISION_TARGET:.0%} target')
        if os.path.exists(BASELINE_PATH):
            with open(BASELINE_PATH, encoding="utf-8") as fh:
                base = json.load(fh)
            if base.get("set_version") == SET_VERSION:
                for key in ("recall", "precision"):
                    now, was = claims_m[key], base["claims"][key]
                    if now < was - REGRESSION_TOLERANCE:
                        problems.append(f'claims {key} regressed: {was:.3f} -> {now:.3f}')
        if problems:
            print("\nEVALUATION GATE FAILED:")
            for p in problems:
                print("  -", p)
            return 1
        print("\nEVALUATION GATE PASSED")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
