"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type User } from "@/lib/api";
import { PERSONAS, ROLE_LABEL, personaName } from "@/lib/personas";

export function TopNav() {
  const [me, setMe] = useState<User | null>(null);
  const [switching, setSwitching] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const load = useCallback(async () => {
    try {
      setMe(await api<User>("/me"));
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
        // Guest mode: sign in as the demo creator automatically so the link
        // is usable by anyone without credentials (Round 2 requirement).
        try {
          await api("/login", { method: "POST", json: { email: "arjun@quillmark" } });
          setMe(await api<User>("/me"));
        } catch {
          setMe(null);
        }
      } else {
        setMe(null);
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, pathname]);

  async function switchPersona(email: string) {
    setSwitching(true);
    try {
      await api("/login", { method: "POST", json: { email } });
      await load();
      router.push("/");
      router.refresh();
    } finally {
      setSwitching(false);
    }
  }

  const link = (href: string, label: string) => {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return (
      <Link
        key={href}
        href={href}
        className={`rounded-md px-2.5 py-1.5 text-sm transition-colors ${
          active ? "bg-foreground/10 font-medium" : "text-muted-foreground hover:text-foreground"
        }`}
      >
        {label}
      </Link>
    );
  };

  return (
    <header className="border-b border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4">
        <Link href="/" className="mr-2 flex items-baseline gap-1.5">
          <span className="text-[17px] font-bold tracking-tight">Canonry</span>
          <span className="text-[11px] text-muted-foreground">● Quillmark workspace</span>
        </Link>
        <nav className="flex items-center gap-0.5">
          {link("/", "Submissions")}
          {link("/new", "New content")}
          {link("/kb", "Knowledge base")}
          {link("/insights", "Insights")}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {me ? (
            <>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {personaName(me.email)} · {ROLE_LABEL[me.role] ?? me.role}
              </span>
              <select
                value={me.email}
                onChange={(e) => void switchPersona(e.target.value)}
                disabled={switching}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
                aria-label="Switch persona"
              >
                {PERSONAS.map((p) => (
                  <option key={p.email} value={p.email}>
                    {p.name}
                  </option>
                ))}
              </select>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">connecting…</span>
          )}
        </div>
      </div>
    </header>
  );
}
