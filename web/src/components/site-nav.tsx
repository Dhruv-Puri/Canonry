"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, LogOut, Menu, PencilLine, X } from "lucide-react";
import { BrandMark } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { initials, ROLE_LABEL, ROLES } from "@/lib/roles";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/new", label: "Write" },
  { href: "/kb", label: "Knowledge base" },
  { href: "/insights", label: "Insights" },
] as const;

export function SiteNav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" || pathname.startsWith("/submissions") : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-40 px-4 pt-3 sm:px-6">
      <div
        className={`mx-auto flex h-14 max-w-6xl items-center gap-3 rounded-full px-3 transition-all duration-500 ${
          scrolled ? "capsule" : "border border-transparent"
        }`}
      >
        <Link href="/" className="flex items-center gap-2 pl-1 pr-2">
          <BrandMark className="size-7" />
          <span className="text-[17px] font-bold tracking-tight text-foreground">Canonry</span>
        </Link>

        <nav aria-label="Main" className="mx-auto hidden items-center gap-1 rounded-full border border-border bg-card/70 p-1 md:flex">
          {LINKS.map(({ href, label }) => (
            <Link key={href} href={href} aria-current={isActive(href) ? "page" : undefined} className="capsule-link">
              {label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto hidden md:block">
          <ProfileMenu />
        </div>

        <button className="btn btn-ghost ml-auto px-2.5 md:hidden" onClick={() => setOpen((o) => !o)} aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>

      {open && (
        <div className="capsule animate-fade-up mx-auto mt-2 max-w-6xl rounded-3xl p-3 md:hidden">
          <nav aria-label="Main" className="grid gap-1">
            {LINKS.map(({ href, label }) => (
              <Link key={href} href={href} aria-current={isActive(href) ? "page" : undefined} className="capsule-link py-2.5 text-[15px]">
                {label}
              </Link>
            ))}
          </nav>
          <div className="mt-2 border-t border-border pt-2">
            <ProfileMenu inline />
          </div>
        </div>
      )}
    </header>
  );
}

/** The person's chip: switch role, change name, or hand the device to someone else. */
function ProfileMenu({ inline = false }: { inline?: boolean }) {
  const { me, update, leave } = useIdentity();
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (!me) return null;

  async function run(fn: () => Promise<void>) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3 transition-colors hover:bg-accent"
      >
        <span className="grid size-8 place-items-center rounded-full bg-gradient-to-br from-brand to-primary text-xs font-bold text-primary-foreground">
          {initials(me.name)}
        </span>
        <span className="text-left leading-tight">
          <span className="block max-w-[160px] truncate text-[13px] font-semibold text-foreground">{me.name}</span>
          <span className="block text-[11px] text-muted-foreground">{ROLE_LABEL[me.role] ?? me.role}</span>
        </span>
        <ChevronDown className={`size-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>

      {open && (
        <div
          role="menu"
          className={`animate-fade-up z-50 w-72 rounded-2xl border border-border bg-card p-2 shadow-float ${inline ? "mt-2" : "absolute right-0 top-12"}`}
        >
          <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Switch role</p>
          {ROLES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              role="menuitemradio"
              aria-checked={me.role === id}
              onClick={() => run(async () => { await update({ role: id }); setOpen(false); })}
              className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left text-sm hover:bg-muted"
            >
              <Icon className="size-4 text-brand" aria-hidden />
              <span className="flex-1">{label}</span>
              {me.role === id && <Check className="size-4 text-brand" strokeWidth={3} aria-hidden />}
            </button>
          ))}
          <div className="my-2 border-t border-border" />
          {renaming ? (
            <form
              className="flex gap-2 px-1"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => { await update({ name }); setRenaming(false); });
              }}
            >
              <input autoFocus maxLength={40} aria-label="Your name" className="field h-9 px-3" value={name} onChange={(e) => setName(e.target.value)} />
              <button className="btn btn-sm btn-primary" disabled={name.trim().length < 2}>Save</button>
            </form>
          ) : (
            <button
              role="menuitem"
              onClick={() => { setName(me.name); setRenaming(true); }}
              className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left text-sm hover:bg-muted"
            >
              <PencilLine className="size-4 text-brand" aria-hidden /> Change name
            </button>
          )}
          <button
            role="menuitem"
            onClick={() => run(leave)}
            className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left text-sm hover:bg-muted"
          >
            <LogOut className="size-4 text-brand" aria-hidden /> Switch person
          </button>
          {error && <p role="alert" className="px-2 pt-1 text-xs text-danger-fg">{error}</p>}
        </div>
      )}
    </div>
  );
}
