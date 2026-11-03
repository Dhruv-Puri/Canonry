"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Award } from "lucide-react";
import { api, CATEGORY_LABEL } from "@/lib/api";

type Scorecard = {
  submissions: number;
  approved: number;
  first_time_right: number;
  sent_back: number;
  avg_first_check_issues: number | null;
  top_rules: { id: string; statement: string; count: number }[];
  top_categories: { category: string; count: number }[];
};

/**
 * Only an agency has this: how its work fares against the client's rules. Clients judge agencies on
 * rework, so the headline is "approved first time"; the rules tripped most say what to brief the team on.
 * A dark "carbon block" (design doc §5.4), so the agency's desk never looks like a creator's or an admin's.
 */
export function AgencyScorecard() {
  const [card, setCard] = useState<Scorecard | null>(null);

  useEffect(() => {
    let alive = true;
    api<Scorecard>("/agency/scorecard")
      .then((c) => alive && setCard(c))
      .catch(() => alive && setCard(null));
    return () => {
      alive = false;
    };
  }, []);

  if (!card) return null;
  const rate = card.approved ? Math.round((100 * card.first_time_right) / card.approved) : null;

  return (
    <section aria-labelledby="scorecard-title" className="carbon-block rounded-2xl p-6 sm:p-7">
      <div className="flex flex-wrap items-center gap-2">
        <Award className="size-4 text-[#d9a77a]" aria-hidden />
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[#d9a77a]">Client scorecard</p>
        <p className="ml-auto text-xs text-[#b9ab99]">What the client sees about your agency&apos;s work</p>
      </div>
      <h2 id="scorecard-title" className="sr-only">Client scorecard</h2>

      <div className="mt-5 grid gap-6 sm:grid-cols-[auto_1fr] sm:items-center">
        <div className="flex items-center gap-4">
          <Ring percent={rate} />
          <div>
            <p className="text-sm font-semibold text-[#f7f1e6]">Approved first time</p>
            <p className="text-xs text-[#b9ab99]">
              {card.approved
                ? `${card.first_time_right} of ${card.approved} approved without a send-back`
                : "Shows once your first draft is approved"}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-px overflow-hidden rounded-xl bg-[#2e2823]">
          <Figure value={card.submissions} label="drafts sent" />
          <Figure value={card.sent_back} label="sent back" warn={card.sent_back > 0} />
          <Figure value={card.avg_first_check_issues ?? "–"} label="issues per first check" />
        </div>
      </div>

      {card.top_rules.length > 0 && (
        <div className="mt-6 border-t border-[#2e2823] pt-5">
          <p className="text-sm font-semibold text-[#f7f1e6]">Brief your team on these client rules</p>
          <ul className="mt-3 space-y-2">
            {card.top_rules.map((r) => (
              <li key={r.id} className="flex items-start gap-3 rounded-lg bg-[#1a1715] px-3 py-2.5">
                <span className="mt-0.5 shrink-0 rounded bg-[#2e2823] px-1.5 py-0.5 font-mono text-[11px] text-[#d9a77a]">
                  {r.id}
                </span>
                <span className="min-w-0 flex-1 text-sm leading-snug text-[#e8dfd2]">{r.statement}</span>
                <span className="shrink-0 text-xs tabular-nums text-[#b9ab99]">{r.count}×</span>
              </li>
            ))}
          </ul>
          <Link href="/kb" className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-[#d9a77a] hover:text-[#f0c49c]">
            Read the client&apos;s full rulebook <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      )}
      {card.top_rules.length === 0 && card.top_categories.length > 0 && (
        <p className="mt-5 text-sm text-[#e8dfd2]">
          Most common: {card.top_categories.map((c) => CATEGORY_LABEL[c.category] ?? c.category).join(", ")}.
        </p>
      )}
    </section>
  );
}

function Figure({ value, label, warn = false }: { value: number | string; label: string; warn?: boolean }) {
  return (
    <div className="bg-[#1a1715] px-4 py-3">
      <p className={`text-2xl font-semibold tabular-nums ${warn ? "text-[#f0b26b]" : "text-[#f7f1e6]"}`}>{value}</p>
      <p className="mt-0.5 text-xs text-[#b9ab99]">{label}</p>
    </div>
  );
}

/** The first-time-right rate as a ring. */
function Ring({ percent }: { percent: number | null }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const p = percent ?? 0;
  return (
    <svg viewBox="0 0 76 76" className="size-20 shrink-0" role="img" aria-label={percent === null ? "No approvals yet" : `${percent}% approved first time`}>
      <circle cx="38" cy="38" r={r} fill="none" stroke="#2e2823" strokeWidth="8" />
      <circle
        cx="38"
        cy="38"
        r={r}
        fill="none"
        stroke="#d9a77a"
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={`${(c * p) / 100} ${c}`}
        transform="rotate(-90 38 38)"
      />
      <text x="38" y="43" textAnchor="middle" fontSize="16" fontWeight="700" fill="#f7f1e6">
        {percent === null ? "–" : `${percent}%`}
      </text>
    </svg>
  );
}
