"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowRight, Check, ChevronRight, LoaderCircle } from "lucide-react";
import { api, ApiError, ENGINE_UNREACHABLE, SIGNED_OUT_EVENT, type AuthMode, type User } from "@/lib/api";
import { ROLES, type Role } from "@/lib/roles";
import { BrandMark } from "@/components/brand";

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
/** After this long without an answer, say the engine is waking up instead of showing a blank page. */
const WAKE_NOTICE_MS = 3_000;
/** After this long, stop waiting and offer "Try again". */
const GIVE_UP_MS = 45_000;
/** Pause between attempts while the engine starts (the proxy answers 5xx until it is up). */
const RETRY_MS = 2_500;

/** The engine is not up yet (connection refused, proxy 5xx): worth asking again. */
function isWaking(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 0 || e.status >= 500);
}

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
    setMe(await api<User>("/me", { method: "PATCH", json: patch }));
  }, []);

  const leave = useCallback(async () => {
    await api("/logout", { method: "POST" });
    setMe(null);
    setState("out");
  }, []);

  if (state === "loading") {
    return elapsed < WAKE_NOTICE_MS
      ? <div className="min-h-dvh" aria-busy="true" />
      : <EngineWaking seconds={Math.floor(elapsed / 1000)} />;
  }
  if (state === "down" && !isPublic) return <EngineDown onRetry={() => void boot()} />;
  if (state === "out" && !isPublic) return <Welcome initial={auth} onJoined={(u) => { setMe(u); setState("in"); }} />;
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

/** Shown after 3 s without an answer: the engine sleeps after a quiet spell and takes a moment to wake. */
function EngineWaking({ seconds }: { seconds: number }) {
  // fills over the usual 30 s, then waits near the end instead of pretending to finish
  const pct = Math.min(92, Math.round((seconds / 30) * 100));
  return (
    <main className="grid min-h-dvh place-items-center px-5" aria-busy="true">
      <div className="surface w-full max-w-md p-8 text-center">
        <BrandMark className="mx-auto size-9" />
        <h1 className="mt-4 text-xl font-bold tracking-tight text-foreground">Waking up the checking engine…</h1>
        <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">
          This happens after a quiet spell and usually takes 20–30 seconds. Canonry opens by itself when it&apos;s ready.
        </p>
        <div className="mt-6 flex items-center gap-3">
          <LoaderCircle className="size-4 shrink-0 animate-spin text-brand motion-reduce:animate-none" aria-hidden />
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full rounded-full bg-brand transition-[width] duration-1000 ease-linear" style={{ width: `${pct}%` }} />
          </div>
          <span className="w-10 text-right text-sm tabular-nums text-muted-foreground">
            <span className="sr-only">Waiting for </span>{seconds}s
          </span>
        </div>
        <p className="sr-only" role="status">Waking up the checking engine. This usually takes 20 to 30 seconds.</p>
      </div>
    </main>
  );
}

/** Shown when the engine does not answer at all; one button tries again. */
function EngineDown({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="grid min-h-dvh place-items-center px-5">
      <div role="alert" className="surface max-w-md p-8 text-center">
        <BrandMark className="mx-auto size-9" />
        <h1 className="mt-4 text-xl font-bold tracking-tight text-foreground">Canonry is not answering</h1>
        <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">{ENGINE_UNREACHABLE}</p>
        <button type="button" onClick={onRetry} className="btn btn-primary mt-6">
          Try again
        </button>
      </div>
    </main>
  );
}

/** Demo workspaces get the guest entry; production workspaces sign in with an account. */
function Welcome({ initial, onJoined }: { initial: AuthMode | null; onJoined: (u: User) => void }) {
  const [auth, setAuth] = useState<AuthMode | null>(initial);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial) return;
    void api<AuthMode>("/auth-mode").then(setAuth).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [initial]);

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

const BENEFITS = [
  "Every issue explained, with the rule or fact behind it",
  "One-click fixes, and people make the final call",
  "Approvals anyone can verify later",
];

function GuestWelcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [role, setRole] = useState<Role>("creator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      // the role is shown under the name in the top bar and can change, so the name stays "Guest"
      onJoined(await api<User>("/join", { method: "POST", json: { name: "Guest", role } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-10 sm:px-6">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="aurora left-[8%] top-[6%] size-[420px] bg-[#f7e2b5]" />
        <div className="aurora right-[6%] bottom-[8%] size-[380px] bg-[#f3cfb4]" style={{ animationDelay: "-7s" }} />
      </div>
      <div className="animate-rise grid w-full max-w-4xl overflow-hidden rounded-3xl border border-border bg-card shadow-card md:grid-cols-[1fr_1.1fr]">
        <section className="flex flex-col gap-10 bg-primary p-8 text-primary-foreground sm:p-10">
          <div className="flex items-center gap-2">
            <BrandMark className="size-8" />
            <span className="text-lg font-bold tracking-tight">Canonry</span>
          </div>
          <div>
            <h1 className="text-3xl font-bold leading-tight tracking-tight text-primary-foreground sm:text-[2.1rem]">
              Catch off-brand content before it goes out.
            </h1>
            <ul className="mt-7 space-y-3.5">
              {BENEFITS.map((b) => (
                <li key={b} className="flex gap-3 text-[15px] leading-snug opacity-90">
                  <Check className="mt-0.5 size-4 shrink-0" strokeWidth={2.6} aria-hidden />
                  {b}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <form
          className="p-8 sm:p-10"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) void start();
          }}
        >
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Try Canonry</h2>
          <p className="mt-1.5 text-foreground-secondary">
            No account needed. You start as a <strong className="text-foreground">{ROLES.find((r) => r.id === role)?.label ?? "Creator"}</strong>
            {role === "creator" ? " (someone who writes marketing content)" : ""}, and a short checklist walks you
            through the rest.
          </p>

          <button type="submit" disabled={busy} className="btn btn-primary btn-lg mt-6 w-full">
            {busy ? "Opening Canonry…" : (
              <>
                {role === "creator" ? "Start the demo" : `Continue as ${ROLES.find((r) => r.id === role)?.label}`}
                <ArrowRight className="btn-arrow size-4" aria-hidden />
              </>
            )}
          </button>

          <details className="group/roles mt-5">
            <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-sm font-medium text-brand hover:underline [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-4 transition-transform group-open/roles:rotate-90" aria-hidden />
              Or choose a different role
            </summary>
          <fieldset className="mt-3 space-y-2.5">
            <legend className="sr-only">Role</legend>
            {ROLES.map(({ id, label, short, icon: Icon }) => {
              const on = role === id;
              return (
                <label
                  key={id}
                  className={`flex cursor-pointer items-center gap-3 rounded-2xl border p-3.5 transition-all has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand ${
                    on ? "border-brand bg-muted ring-2 ring-[var(--ring-glow)]" : "border-border hover:border-border-strong hover:bg-muted/50"
                  }`}
                >
                  <input type="radio" name="role" value={id} checked={on} onChange={() => setRole(id)} className="sr-only" />
                  <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${on ? "bg-primary text-primary-foreground" : "bg-muted text-brand"}`}>
                    <Icon className="size-5" strokeWidth={1.9} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-foreground">{label}</span>
                    <span className="block text-sm leading-snug text-muted-foreground">{short}</span>
                  </span>
                  {on && <Check className="size-4 shrink-0 text-brand" strokeWidth={3} aria-hidden />}
                </label>
              );
            })}
          </fieldset>
          </details>

          {error && (
            <p role="alert" className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
              {error}
            </p>
          )}
          <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
            Switch roles any time from the menu at the top right. This is a shared demo workspace, so please don&apos;t
            enter real brand material.
          </p>
        </form>
      </div>
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
