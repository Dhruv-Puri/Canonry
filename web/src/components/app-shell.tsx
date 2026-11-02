"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  BookOpenCheck,
  CircleHelp,
  ClipboardCheck,
  LayoutGrid,
  PenSquare,
  Plug,
  type LucideIcon,
} from "lucide-react";
import { BrandMark } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { GuidePanel, useGuide } from "@/components/guide";
import { ProfileMenu } from "@/components/site-nav";
import { canReview, navLinksFor, roleHome, type NavItem } from "@/lib/roles";

const ICON: Record<NavItem["icon"], LucideIcon> = {
  home: LayoutGrid,
  write: PenSquare,
  review: ClipboardCheck,
  rules: BookOpenCheck,
  reports: BarChart3,
  plug: Plug,
};

/** Which nav item a route belongs to (a submission belongs to the list it was opened from). */
function useActive() {
  const path = usePathname();
  const { me } = useIdentity();
  const onSubmission = path.startsWith("/submissions");
  return (href: string) => {
    if (href === "/review") return path.startsWith("/review") || (canReview(me?.role) && onSubmission);
    if (href === "/admin") return path === "/admin";
    if (href === "/admin/api") return path.startsWith("/admin/api");
    if (href === "/agency") return path.startsWith("/agency") || (me?.role === "agency" && onSubmission);
    if (href === "/") return path === "/" || (me?.role === "creator" && onSubmission);
    return path.startsWith(href);
  };
}

/** Lives outside the identity gate: a role switch remounts the app, the toast must survive it. */
export function Toast() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let t: number | undefined;
    const on = (e: Event) => {
      setText((e as CustomEvent<string>).detail);
      window.clearTimeout(t);
      t = window.setTimeout(() => setText(null), 4500);
    };
    window.addEventListener("canonry:toast", on);
    return () => window.removeEventListener("canonry:toast", on);
  }, []);
  if (!text) return null;
  return (
    <div role="status" className="animate-fade-up fixed left-1/2 top-4 z-[60] -translate-x-1/2 rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background shadow-float">
      {text}
    </div>
  );
}

function HelpButton({ className = "" }: { className?: string }) {
  const { on, start } = useGuide();
  return (
    <button
      type="button"
      onClick={start}
      aria-label={on ? "The guide is open" : "Show the guide"}
      title="Show the guide"
      className={`grid size-9 place-items-center rounded-full border border-border bg-card text-foreground-secondary transition-colors hover:text-foreground ${className}`}
    >
      <CircleHelp className="size-[18px]" aria-hidden />
    </button>
  );
}

/**
 * The signed-in app: a quiet sidebar on desktop and a bottom tab bar on phones.
 * Each role sees only its own work (lib/roles.ts navLinksFor).
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { me } = useIdentity();
  const links = navLinksFor(me?.role);
  const isActive = useActive();
  const home = roleHome(me?.role);
  const { on: guideOn } = useGuide();

  // public pages (verify) for signed-out visitors: no app menu, just the brand
  if (!me) {
    return (
      <div className="flex min-h-dvh flex-col">
        <header className="flex h-16 items-center gap-2 border-b border-border px-4 sm:px-8">
          <BrandMark className="size-7" />
          <span className="text-[17px] font-bold tracking-tight text-foreground">Canonry</span>
          <span className="ml-auto text-xs text-muted-foreground">Public verification</span>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-8">{children}</main>
      </div>
    );
  }

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[232px_minmax(0,1fr)]">
      {/* ---- sidebar (desktop) ---- */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-border bg-card/60 px-3 py-5 backdrop-blur md:flex">
        <Link href={home} className="flex items-center gap-2 px-2">
          <BrandMark className="size-7" />
          <span className="text-[17px] font-bold tracking-tight text-foreground">Canonry</span>
        </Link>
        <div className="mx-2 mt-4 rounded-xl border border-border bg-background/70 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Workspace</p>
          <p className="text-sm font-semibold text-foreground">Quillmark Analytics</p>
        </div>
        <nav aria-label="Main" className="mt-5 grid gap-0.5">
          {links.map(({ href, label, icon }) => {
            const Icon = ICON[icon];
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                  active ? "bg-foreground text-background" : "text-foreground-secondary hover:bg-muted hover:text-foreground"
                }`}
              >
                <Icon className="size-[18px]" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className={`mt-auto space-y-3 px-2 ${guideOn ? "invisible" : ""}`}>
          <p className="text-xs leading-relaxed text-muted-foreground">
            A shared demo workspace. Please don&apos;t enter real brand material.
          </p>
        </div>
      </aside>

      <div className="flex min-h-dvh min-w-0 flex-col">
        {/* ---- top bar ---- */}
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur sm:px-6">
          <Link href={home} className="flex items-center gap-2 md:hidden">
            <BrandMark className="size-7" />
            <span className="text-[17px] font-bold tracking-tight text-foreground">Canonry</span>
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <HelpButton />
            <ProfileMenu compact />
          </div>
        </header>

        <main className={`mx-auto w-full max-w-6xl flex-1 px-4 pt-6 sm:px-8 md:pt-8 ${guideOn ? "pb-80 md:pb-16" : "pb-28 md:pb-16"}`}>
          {children}
        </main>

        {/* ---- tab bar (phones) ---- */}
        <nav
          aria-label="Main"
          className="fixed inset-x-0 bottom-0 z-40 grid border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
          style={{ gridTemplateColumns: `repeat(${links.length}, minmax(0, 1fr))` }}
        >
          {links.map(({ href, label, icon }) => {
            const Icon = ICON[icon];
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-[60px] flex-col items-center justify-center gap-1 text-[11px] font-medium ${
                  active ? "text-foreground" : "text-muted-foreground"
                }`}
              >
                <Icon className={`size-5 ${active ? "text-brand" : ""}`} aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
      <GuidePanel />
    </div>
  );
}
