"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Rule = { id: string; statement: string; do_example: string | null; dont_example: string | null; severity: string; status: string; vague_flag: string | null };
type Fact = { id: string; text: string; owner: string; valid_from: string | null; valid_to: string | null; confidential: number };
type Term = { id: string; preferred: string; avoid: string | null; note: string | null };

export default function KBPage() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [terms, setTerms] = useState<Term[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [r, f, t] = await Promise.all([
          api<{ rules: Rule[] }>("/rules"),
          api<{ facts: Fact[] }>("/facts"),
          api<{ terms: Term[] }>("/terms"),
        ]);
        setRules(r.rules);
        setFacts(f.facts);
        setTerms(t.terms);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Knowledge base</h1>
        <p className="text-sm text-muted-foreground">
          The workspace’s single source of truth: every check cites an entry from here.
        </p>
      </div>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40">{error}</p>}

      <Tabs defaultValue="rules">
        <TabsList>
          <TabsTrigger value="rules">Rules {rules ? `(${rules.length})` : ""}</TabsTrigger>
          <TabsTrigger value="facts">Facts {facts ? `(${facts.length})` : ""}</TabsTrigger>
          <TabsTrigger value="terms">Terms {terms ? `(${terms.length})` : ""}</TabsTrigger>
        </TabsList>

        <TabsContent value="rules" className="space-y-1.5 pt-2">
          {rules?.map((r) => (
            <div key={r.id} className="rounded-lg border border-border bg-card p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <code className="text-xs font-semibold">{r.id}</code>
                <span className="capitalize text-xs text-muted-foreground">{r.severity}</span>
                {r.status !== "approved" && (
                  <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800">{r.status}</span>
                )}
                {r.vague_flag && (
                  <span className="rounded-full border border-dashed border-amber-300 px-1.5 py-0.5 text-[11px] text-amber-700">
                    possibly unclear: {r.vague_flag.replace("vague_", "")}
                  </span>
                )}
              </div>
              <p className="mt-1">{r.statement}</p>
              {(r.do_example || r.dont_example) && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.do_example && <>Do: “{r.do_example}” </>}
                  {r.dont_example && <>· Don’t: “{r.dont_example}”</>}
                </p>
              )}
            </div>
          ))}
        </TabsContent>

        <TabsContent value="facts" className="space-y-1.5 pt-2">
          {facts?.map((f) => (
            <div key={f.id} className="rounded-lg border border-border bg-card p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <code className="font-semibold">{f.id}</code>
                <span>owner: {f.owner}</span>
                {(f.valid_from || f.valid_to) && (
                  <span>
                    valid {f.valid_from ?? "…"} → {f.valid_to ?? "open"}
                  </span>
                )}
                {f.confidential ? (
                  <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-violet-800 dark:bg-violet-950 dark:text-violet-200">
                    confidential
                  </span>
                ) : null}
              </div>
              <p className="mt-1">{f.text}</p>
            </div>
          ))}
        </TabsContent>

        <TabsContent value="terms" className="space-y-1.5 pt-2">
          {terms?.map((t) => (
            <div key={t.id} className="rounded-lg border border-border bg-card p-3 text-sm">
              <p>
                <span className="font-medium">{t.preferred}</span>
                {t.avoid && <span className="text-muted-foreground"> — not “{t.avoid}”</span>}
              </p>
              {t.note && <p className="mt-0.5 text-xs text-muted-foreground">{t.note}</p>}
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  );
}
