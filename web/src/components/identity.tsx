"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowRight, Check } from "lucide-react";
import { api, ApiError, SIGNED_OUT_EVENT, type AuthMode, type User } from "@/lib/api";
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
export function IdentityGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  const [me, setMe] = useState<User | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [state, setState] = useState<"loading" | "in" | "out">("loading");

  const refresh = useCallback(async () => {
    try {
      setMe(await api<User>("/me"));
      setState("in");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        setState("out");
      } else {
        setState("in"); // engine hiccup: let pages show their own errors
      }
    }
  }, []);

  useEffect(() => {
    void api<AuthMode>("/auth-mode").then((mode) => setDemoMode(mode.demo_mode)).catch(() => setDemoMode(false));
    void refresh();
    const onOut = () => {
      setMe(null);
      setState("out");
    };
    window.addEventListener(SIGNED_OUT_EVENT, onOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onOut);
  }, [refresh]);

  const update = useCallback(async (patch: { name?: string; role?: Role }) => {
    setMe(await api<User>("/me", { method: "PATCH", json: patch }));
  }, []);

  const leave = useCallback(async () => {
    await api("/logout", { method: "POST" });
    setMe(null);
    setState("out");
  }, []);

  if (state === "loading") return <div className="min-h-dvh" aria-busy="true" />;
  if (state === "out" && !isPublic) return <Welcome onJoined={(u) => { setMe(u); setState("in"); }} />;
  // remount everything when the person or their role changes, so every view
  // reloads with what the new role may see
  return (
    <IdentityContext.Provider value={{ me, demoMode, refresh, update, leave }}>
      <div key={`${me?.id}:${me?.role}`} className="contents">
        {children}
      </div>
    </IdentityContext.Provider>
  );
}

function Welcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [auth, setAuth] = useState<AuthMode | null>(null);
  const [mode, setMode] = useState<"login" | "join">("login");
  const [loginEmail, setLoginEmail] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [invitation, setInvitation] = useState("");
  const [invitedRole, setInvitedRole] = useState("");
  const [role, setRole] = useState<Role>("creator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api<AuthMode>("/auth-mode").then(setAuth).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    const url = new URL(window.location.href);
    const token = url.searchParams.get("invite");
    if (token) {
      setInvitation(token);
      url.searchParams.delete("invite");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, []);

  useEffect(() => {
    if (!auth || auth.demo_mode || !invitation.trim()) {
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
  }, [auth, invitation]);

  const demo = auth?.demo_mode === true;
  const valid = (mode === "login" ? loginEmail.trim().length >= 3 : email.trim().length >= 3)
    && (mode === "login" ? (demo || (loginPassword.length >= 12 && loginPassword.length <= 256)) : (password.length >= (demo ? 0 : 12)
      && password.length <= 256 && name.trim().length >= 2 && name.trim().length <= 40 && (demo || invitedRole.length > 0)));

  async function submit() {
    if (!demo && mode === "login" && invitation.trim()) {
      setMode("join");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        const user = await api<User>("/login", { method: "POST", json: { email: loginEmail.trim(), password: loginPassword || undefined } });
        onJoined(user);
      } else {
        const user = await api<User>("/join", { method: "POST", json: demo
          ? { name: name.trim(), email: email.trim(), role }
          : { name: name.trim(), email: email.trim(), password, invitation: invitation.trim() } });
        onJoined(user);
      }
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
          {!auth ? "Connecting to the workspace…" : demo ? "Demo mode: sign in as a seeded persona or create a walkthrough identity." : "Sign in with your account, or use an invitation from your workspace admin to join."}
        </p>
        {!demo && <label className="mt-5 block"><span className="text-sm font-semibold text-foreground">Invitation token {mode === "login" ? "(optional)" : "(required)"}</span><input className="field mt-2 h-11 rounded-2xl px-4 text-sm" placeholder="Paste your invitation token" value={invitation} onChange={(e) => setInvitation(e.target.value)} /></label>}

        {mode === "join" && (
          <label className="mt-8 block">
            <span className="text-sm font-semibold text-foreground">Your name</span>
            <input autoFocus maxLength={40} className="field mt-2 h-12 rounded-2xl px-4 text-base" placeholder="e.g. Priya Raman" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label className="mt-5 block">
          <span className="text-sm font-semibold text-foreground">Email</span>
          <input type="email" autoComplete="email" className="field mt-2 h-12 rounded-2xl px-4 text-base" placeholder={demo ? "maya@quillmark" : "you@company.com"} value={mode === "login" ? loginEmail : email} onChange={(e) => mode === "login" ? setLoginEmail(e.target.value) : setEmail(e.target.value)} />
        </label>
        {(mode === "join" || (!demo && mode === "login")) && (
          <label className="mt-4 block">
            <span className="text-sm font-semibold text-foreground">Password {mode === "join" ? "(12+ characters)" : ""}</span>
            <input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={demo ? undefined : 12} maxLength={256} className="field mt-2 h-12 rounded-2xl px-4 text-base" value={mode === "login" ? loginPassword : password} onChange={(e) => mode === "login" ? setLoginPassword(e.target.value) : setPassword(e.target.value)} />
          </label>
        )}
        {!demo && mode === "join" && invitedRole && <p className="mt-3 text-sm text-muted-foreground">Invitation grants the {invitedRole} role for {email}.</p>}
        {demo && mode === "join" && (
          <fieldset className="mt-6">
            <legend className="text-sm font-semibold text-foreground">Demo role</legend>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              {ROLES.map(({ id, label, does, icon: Icon }) => {
                const on = role === id;
                return <label key={id} className={`surface relative flex cursor-pointer gap-3 p-4 transition-all ${on ? "border-brand ring-2 ring-[var(--ring-glow)]" : "surface-interactive"}`}>
                  <input type="radio" name="role" value={id} checked={on} onChange={() => setRole(id)} className="sr-only" />
                  <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${on ? "bg-primary text-primary-foreground" : "bg-muted text-brand"}`}><Icon className="size-5" strokeWidth={1.9} /></span>
                  <span className="min-w-0"><span className="block font-semibold text-foreground">{label}</span><span className="block text-sm leading-snug text-muted-foreground">{does}</span></span>
                  {on && <Check className="absolute right-3 top-3 size-4 text-brand" strokeWidth={3} aria-hidden />}
                </label>;
              })}
            </div>
          </fieldset>
        )}

        {error && (
          <p role="alert" className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
            {error}
          </p>
        )}
        {demo && <button type="button" onClick={() => setRole("creator")} className="sr-only">Use Creator role</button>}
        <button type="button" onClick={() => { setMode(mode === "login" ? "join" : "login"); setError(null); }} className="mt-5 text-sm font-semibold text-brand underline underline-offset-4">
          {mode === "login" ? (demo ? "Create a demo identity" : "Join with an invitation") : "Back to sign in"}
        </button>
        <button type="submit" disabled={!valid || busy || !auth || (mode === "join" && !demo && !invitedRole)} className="btn btn-primary btn-lg mt-5 w-full sm:w-auto">
          {busy ? "Signing in…" : <>{mode === "login" ? "Sign in" : "Join workspace"} <ArrowRight className="btn-arrow size-4" aria-hidden /></>}
        </button>
        <p className="mt-4 text-xs text-muted-foreground">
          {demo ? "Demo identities and selectable roles are enabled only because CANONRY_DEMO_MODE is on." : "Workspace roles are assigned by admins through single-use invitations; you cannot elevate your own account."}
        </p>
      </form>
    </main>
  );
}
