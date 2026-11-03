"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowRight, BadgeCheck, Check, ChevronDown, Info, Quote, Wand2 } from "lucide-react";
import { forgetVisit, hasVisited, rememberFirstTime, useGuide } from "@/components/guide";
import { api, ApiError, SIGNED_OUT_EVENT, type AuthMode, type User } from "@/lib/api";
import { ROLES, type Role } from "@/lib/roles";
import { BrandMark } from "@/components/brand";
import { HeroDemo } from "@/components/hero-demo";
import { GuideCharacter } from "@/components/tour-figures";
import { EngineDown, EngineLoading, GIVE_UP_MS, isWaking, RETRY_MS } from "@/components/engine-status";

type Identity = {
  me: User | null;
  demoMode: boolean;
  /** re-read the current person (after a role or name change) */
  refresh: () => Promise<void>;
  update: (patch: { name?: string; role?: Role }) => Promise<void>;
  leave: () => Promise<void>;
};

const IdentityContext = createContext<Identity | null>(null);

export function useIdentity(): Identity {
  const ctx = useContext(IdentityContext);
  if (!ctx) throw new Error("useIdentity must be used inside <IdentityGate>");
  return ctx;
}

/** Routes anyone may open without signing in (the public seal check). */
const PUBLIC_PATHS = ["/verify/"];

/**
 * Demo workspaces offer disposable personas; production requires an invited
 * account and password. Until signed in, the welcome screen replaces the app,
 * except on public routes, which render for signed-out visitors too.
 */
export function IdentityGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const [me, setMe] = useState<User | null>(null);
  const [auth, setAuth] = useState<AuthMode | null>(null);
  const [state, setState] = useState<"loading" | "in" | "out" | "down">("loading");
  const [elapsed, setElapsed] = useState(0);
  // each boot gets a number; answers that arrive for an older boot (before "Try again") are ignored
  const bootRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setMe(await api<User>("/me"));
      setState("in");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        setState("out");
      } else {
        // the engine is asleep or unreachable: say so once, instead of every page
        // rendering for nobody (empty lists, "this page is for admins")
        setState("down");
      }
    }
  }, []);

  /**
   * First load. A free-tier engine can take 20–30 s to wake: keep asking (quietly
   * for 3 s, then with a "waking up" card) and only give up after 45 s.
   */
  const boot = useCallback(async () => {
    const id = ++bootRef.current;
    const started = Date.now();
    const current = () => bootRef.current === id;
    setState("loading");
    setElapsed(0);
    const ask = async <T,>(path: string): Promise<T> => {
      for (;;) {
        try {
          return await api<T>(path);
        } catch (e) {
          if (!isWaking(e) || Date.now() - started > GIVE_UP_MS || !current()) throw e;
          await new Promise((r) => setTimeout(r, RETRY_MS));
          if (!current()) throw e;
        }
      }
    };
    let user: User | null = null;
    try {
      user = await ask<User>("/me");
    } catch (e) {
      if (!current()) return;
      if (!(e instanceof ApiError && e.status === 401)) {
        setState("down");
        return;
      }
    }
    // the engine has answered, so this is quick; the welcome screen needs it
    const mode = await ask<AuthMode>("/auth-mode").catch(() => null);
    if (!current()) return;
    setAuth(mode);
    setMe(user);
    setState(user ? "in" : "out");
  }, []);

  useEffect(() => {
    void boot();
    const onOut = () => {
      setMe(null);
      setState("out");
    };
    window.addEventListener(SIGNED_OUT_EVENT, onOut);
    return () => {
      bootRef.current++;
      window.removeEventListener(SIGNED_OUT_EVENT, onOut);
    };
  }, [boot]);

  // the counter on the waking card; past 45 s the "not answering" screen takes over
  useEffect(() => {
    if (state !== "loading") return;
    const started = Date.now();
    const t = window.setInterval(() => {
      const ms = Date.now() - started;
      setElapsed(ms);
      if (ms > GIVE_UP_MS + RETRY_MS) setState((s) => (s === "loading" ? "down" : s));
    }, 1000);
    return () => window.clearInterval(t);
  }, [state]);

  const update = useCallback(async (patch: { name?: string; role?: Role }) => {
    const changed = await api<User>("/me", { method: "PATCH", json: patch });
    // keep what the reply leaves out (an older engine omitted the email, so My work lost its drafts)
    setMe((prev) => (prev ? { ...prev, ...changed } : changed));
  }, []);

  const leave = useCallback(async () => {
    try {
      await api("/logout", { method: "POST" });
    } finally {
      // Logging out forgets this visit's guide progress; the browser keeps having seen the intro
      // and the tours, so switching profile this way does not replay them.
      forgetVisit();
      setMe(null);
      setState("out");
    }
  }, []);

  if (state === "loading") return <EngineLoading elapsedMs={elapsed} />;
  if (state === "down" && !isPublic) return <EngineDown onRetry={() => void boot()} />;
  if (state === "out" && !isPublic) return <Welcome onJoined={(u) => { setMe(u); setState("in"); }} />;
  // remount everything when the person or their role changes, so every view
  // reloads with what the new role may see
  return (
    <IdentityContext.Provider value={{ me, demoMode: auth?.demo_mode ?? false, refresh, update, leave }}>
      <div key={`${me?.id}:${me?.role}`} className="contents">
        {children}
      </div>
    </IdentityContext.Provider>
  );
}

/** Demo workspaces get the guest entry; production workspaces sign in with an account. */
function Welcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [auth, setAuth] = useState<AuthMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api<AuthMode>("/auth-mode").then(setAuth).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (!auth) {
    return (
      <main className="grid min-h-dvh place-items-center px-5" aria-busy={!error}>
        <p className={error ? "text-sm text-danger-fg" : "text-sm text-muted-foreground"} role={error ? "alert" : undefined}>
          {error ?? "Opening Canonry…"}
        </p>
      </main>
    );
  }
  return auth.demo_mode ? <GuestWelcome onJoined={onJoined} /> : <AccountWelcome onJoined={onJoined} />;
}

/** Each role's accent, the same colours the workspace uses once you are in (globals.css: html[data-role]). */
const ROLE_ACCENT: Record<Role, { accent: string; tint: string }> = {
  creator: { accent: "#6f4e37", tint: "#f3e9df" },
  reviewer: { accent: "#2e5a44", tint: "#e6efe9" },
  agency: { accent: "#8a4f0e", tint: "#fbefdf" },
  admin: { accent: "#0f0e0c", tint: "#ebe6df" },
};

const PROOF = [
  { icon: Quote, text: "Every issue cites its source" },
  { icon: Wand2, text: "One-click fixes, a person decides" },
  { icon: BadgeCheck, text: "Approvals anyone can verify" },
];

function GuestWelcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [role, setRole] = useState<Role>("creator");
  // first visit in this browser: offer the walkthrough; a returning visitor sees Canonry as before
  const [guided, setGuided] = useState(false);
  const { start: startGuide } = useGuide();
  useEffect(() => {
    setGuided(!hasVisited());
  }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = ROLES.find((r) => r.id === role);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      // the role is shown under the name in the top bar and can change, so the name stays "Guest"
      const user = await api<User>("/join", { method: "POST", json: { name: "Guest", role } });
      rememberFirstTime(guided);
      if (guided) startGuide();
      onJoined(user);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh lg:grid-cols-2">
      {/* ---- the story: what Canonry is, shown working ---- */}
      <section className="welcome-hero relative flex flex-col gap-6 overflow-hidden px-6 py-8 sm:px-12 lg:items-center lg:justify-center lg:py-10">
        {/* the logo sits in the corner, so the two halves' content can be centred alike */}
        <div className="flex items-center gap-2.5 lg:absolute lg:left-12 lg:top-9">
          <BrandMark className="size-8" />
          <span className="text-lg font-bold tracking-tight">Canonry</span>
        </div>
        <div className="w-full lg:max-w-[480px]">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#e2b88f]">Brand review before you publish</p>
          <h1 className="mt-3 text-4xl font-bold leading-[1.08] tracking-tight text-[#fbf6ee] xl:text-[2.75rem]">
            Every word on brand, before it goes out.
          </h1>
          <p className="mt-3 max-w-md text-base leading-relaxed text-[#e9dccb] xl:text-[17px]">
            Canonry checks drafts against the brand&apos;s own rules and facts, explains every issue, and leaves the decision
            to a person.
          </p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {PROOF.map(({ icon: Icon, text }) => (
              <li key={text} className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.07] px-3 py-1.5 text-sm text-[#f3e8d9]">
                <Icon className="size-3.5 text-[#e2b88f]" aria-hidden /> {text}
              </li>
            ))}
          </ul>
          <div className="welcome-preview mt-8 hidden lg:block" aria-hidden>
            <HeroDemo />
          </div>
        </div>
      </section>

      {/* ---- the choice: one role, one switch, one button ---- */}
      <section className="flex items-center justify-center px-5 py-8 sm:px-12 lg:py-10">
        {/* no entrance animation: the choices must not move under a quick click or tap */}
        <form
          className="w-full max-w-[480px]"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) void start();
          }}
        >
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Try Canonry</h2>
          <p className="mt-1 text-foreground-secondary">Pick a role. No account needed; switch any time.</p>

          <fieldset className="mt-5 grid grid-cols-2 gap-3">
            <legend className="sr-only">Role</legend>
            {ROLES.map(({ id, label, short, icon: Icon }) => {
              const on = role === id;
              const c = ROLE_ACCENT[id];
              return (
                <label
                  key={id}
                  style={{ "--card-accent": c.accent, "--card-tint": c.tint } as React.CSSProperties}
                  className={`role-card ${on ? "is-on" : ""}`}
                >
                  <input type="radio" name="role" value={id} checked={on} onChange={() => setRole(id)} className="sr-only" />
                  <span className="role-card-icon">
                    <Icon className="size-[18px]" strokeWidth={2} aria-hidden />
                  </span>
                  <span className="mt-3 block font-semibold text-foreground">{label}</span>
                  <span className="mt-0.5 block text-[13px] leading-snug text-muted-foreground">{short}</span>
                  {on && <Check className="absolute right-3 top-3 size-4 text-[var(--card-accent)]" strokeWidth={3} aria-hidden />}
                </label>
              );
            })}
          </fieldset>

          <label className="mt-4 flex cursor-pointer items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 transition-colors has-[:checked]:border-brand/40 has-[:checked]:bg-[var(--warning-bg)]">
            <GuideCharacter className={`h-11 w-9 shrink-0 transition-opacity ${guided ? "opacity-100" : "opacity-40 grayscale"}`} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-foreground">Show me around (first time here)</span>
              <span className="block text-xs text-muted-foreground">A quick tour, then a guide that points at each next step.</span>
            </span>
            <input type="checkbox" checked={guided} onChange={(e) => setGuided(e.target.checked)} className="switch" />
          </label>

          {error && (
            <p role="alert" className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy} className="btn btn-primary btn-lg mt-5 w-full">
            {busy ? "Opening Canonry…" : <>Continue as guest <ArrowRight className="btn-arrow size-4" aria-hidden /></>}
          </button>
          <p className="mt-2 text-center text-xs text-muted-foreground">
            You start as <strong className="font-semibold text-foreground">{chosen?.label}</strong>
          </p>

          <details className="group mt-5 rounded-xl border border-border bg-muted/50 px-4 py-2.5 text-xs leading-relaxed text-foreground-secondary">
            <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold text-foreground">
              <Info className="size-3.5 text-brand" aria-hidden />
              A shared demo, on purpose
              <ChevronDown className="ml-auto size-3.5 transition-transform group-open:rotate-180" aria-hidden />
            </summary>
            <p className="mt-2">
              Every visitor uses one sample workspace and can switch between all four roles, so you can try each side of a
              review. A real deployment runs in production mode: invited accounts with their own passwords, the role fixed
              by the invitation, and agency partners who only ever see their own work. Please don&apos;t enter real brand
              material here.
            </p>
          </details>
        </form>
      </section>
    </main>
  );
}

/** Production workspaces: sign in with a password, or join with a one-use invitation. */
function AccountWelcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [mode, setMode] = useState<"login" | "join">("login");
  const [loginEmail, setLoginEmail] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [invitation, setInvitation] = useState("");
  const [invitedRole, setInvitedRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("invite");
    if (token) {
      setInvitation(token);
      url.searchParams.delete("invite");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, []);

  useEffect(() => {
    if (!invitation.trim()) {
      setInvitedRole("");
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      api<{ email: string; role: string }>(`/invitations/${encodeURIComponent(invitation.trim())}`)
        .then((info) => { if (active) { setEmail(info.email); setInvitedRole(info.role); setMode("join"); setError(null); } })
        .catch((e) => { if (active) { setInvitedRole(""); setError(e instanceof Error ? e.message : String(e)); } });
    }, 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [invitation]);

  const valid = mode === "login"
    ? loginEmail.trim().length >= 3 && loginPassword.length >= 12 && loginPassword.length <= 256
    : email.trim().length >= 3 && password.length >= 12 && password.length <= 256
      && name.trim().length >= 2 && name.trim().length <= 40 && invitedRole.length > 0;

  async function submit() {
    if (mode === "login" && invitation.trim()) {
      setMode("join");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const user = mode === "login"
        ? await api<User>("/login", { method: "POST", json: { email: loginEmail.trim(), password: loginPassword } })
        : await api<User>("/join", { method: "POST", json: { name: name.trim(), email: email.trim(), password, invitation: invitation.trim() } });
      onJoined(user);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-5 py-12">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="aurora left-[8%] top-[6%] size-[420px] bg-[#f7e2b5]" />
        <div className="aurora right-[6%] bottom-[8%] size-[380px] bg-[#f3cfb4]" style={{ animationDelay: "-7s" }} />
      </div>
      <form
        className="animate-rise w-full max-w-2xl"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) void submit();
        }}
      >
        <div className="flex items-center gap-2">
          <BrandMark className="size-8" />
          <span className="text-lg font-bold tracking-tight text-foreground">Canonry</span>
        </div>
        <h1 className="display mt-8 text-[clamp(2.4rem,6vw,3.6rem)]">
          {mode === "login" ? <>Welcome <span className="ink-gradient">back</span></> : <>Join the <span className="ink-gradient">workspace</span></>}
        </h1>
        <p className="mt-4 max-w-lg text-lg text-foreground-secondary">
          Sign in with your account, or use an invitation from your workspace admin to join.
        </p>
        <label className="mt-5 block"><span className="text-sm font-semibold text-foreground">Invitation token {mode === "login" ? "(optional)" : "(required)"}</span><input className="field mt-2 h-11 rounded-2xl px-4 text-sm" placeholder="Paste your invitation token" value={invitation} onChange={(e) => setInvitation(e.target.value)} /></label>

        {mode === "join" && (
          <label className="mt-8 block">
            <span className="text-sm font-semibold text-foreground">Your name</span>
            <input autoFocus maxLength={40} className="field mt-2 h-12 rounded-2xl px-4 text-base" placeholder="e.g. Priya Raman" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label className="mt-5 block">
          <span className="text-sm font-semibold text-foreground">Email</span>
          <input type="email" autoComplete="email" className="field mt-2 h-12 rounded-2xl px-4 text-base" placeholder="you@company.com" value={mode === "login" ? loginEmail : email} onChange={(e) => mode === "login" ? setLoginEmail(e.target.value) : setEmail(e.target.value)} />
        </label>
        <label className="mt-4 block">
          <span className="text-sm font-semibold text-foreground">Password {mode === "join" ? "(12+ characters)" : ""}</span>
          <input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={12} maxLength={256} className="field mt-2 h-12 rounded-2xl px-4 text-base" value={mode === "login" ? loginPassword : password} onChange={(e) => mode === "login" ? setLoginPassword(e.target.value) : setPassword(e.target.value)} />
        </label>
        {mode === "join" && invitedRole && <p className="mt-3 text-sm text-muted-foreground">Invitation grants the {invitedRole} role for {email}.</p>}

        {error && (
          <p role="alert" className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
            {error}
          </p>
        )}
        <button type="button" onClick={() => { setMode(mode === "login" ? "join" : "login"); setError(null); }} className="mt-5 text-sm font-semibold text-brand underline underline-offset-4">
          {mode === "login" ? "Join with an invitation" : "Back to sign in"}
        </button>
        <button type="submit" disabled={!valid || busy} className="btn btn-primary btn-lg mt-5 w-full sm:w-auto">
          {busy ? "Signing in…" : <>{mode === "login" ? "Sign in" : "Join workspace"} <ArrowRight className="btn-arrow size-4" aria-hidden /></>}
        </button>
        <p className="mt-4 text-xs text-muted-foreground">
          Workspace roles are assigned by admins through single-use invitations; you cannot elevate your own account.
        </p>
      </form>
    </main>
  );
}
