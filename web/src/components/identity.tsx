"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { api, ApiError, SIGNED_OUT_EVENT, type User } from "@/lib/api";
import { ROLES, type Role } from "@/lib/roles";
import { BrandMark } from "@/components/brand";

type Identity = {
  me: User | null;
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

/**
 * No login: whoever opens Canonry names themselves and picks a role. Until they
 * have, the welcome screen replaces the whole app.
 */
export function IdentityGate({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<User | null>(null);
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
  if (state === "out") return <Welcome onJoined={(u) => { setMe(u); setState("in"); }} />;
  // remount everything when the person or their role changes, so every view
  // reloads with what the new role may see
  return (
    <IdentityContext.Provider value={{ me, refresh, update, leave }}>
      <div key={`${me?.id}:${me?.role}`} className="contents">
        {children}
      </div>
    </IdentityContext.Provider>
  );
}

function Welcome({ onJoined }: { onJoined: (u: User) => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("creator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = name.trim().length >= 2 && name.trim().length <= 40;

  async function join() {
    setBusy(true);
    setError(null);
    try {
      onJoined(await api<User>("/join", { method: "POST", json: { name: name.trim(), role } }));
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
          if (valid && !busy) void join();
        }}
      >
        <div className="flex items-center gap-2">
          <BrandMark className="size-8" />
          <span className="text-lg font-bold tracking-tight text-foreground">Canonry</span>
        </div>
        <h1 className="display mt-8 text-[clamp(2.4rem,6vw,3.6rem)]">
          Who’s in the <span className="ink-gradient">workspace</span> today?
        </h1>
        <p className="mt-4 max-w-lg text-lg text-foreground-secondary">
          No account needed. Tell us your name and the hat you’re wearing; you can switch roles any time from your profile.
        </p>

        <label className="mt-8 block">
          <span className="text-sm font-semibold text-foreground">Your name</span>
          <input
            autoFocus
            maxLength={40}
            className="field mt-2 h-12 rounded-2xl px-4 text-base"
            placeholder="e.g. Priya Raman"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <fieldset className="mt-6">
          <legend className="text-sm font-semibold text-foreground">Your role</legend>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {ROLES.map(({ id, label, does, icon: Icon }) => {
              const on = role === id;
              return (
                <label
                  key={id}
                  className={`surface relative flex cursor-pointer gap-3 p-4 transition-all has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--ring)] ${
                    on ? "border-brand ring-2 ring-[var(--ring-glow)]" : "surface-interactive"
                  }`}
                >
                  <input type="radio" name="role" value={id} checked={on} onChange={() => setRole(id)} className="sr-only" />
                  <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${on ? "bg-primary text-primary-foreground" : "bg-muted text-brand"}`}>
                    <Icon className="size-5" strokeWidth={1.9} />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-foreground">{label}</span>
                    <span className="block text-sm leading-snug text-muted-foreground">{does}</span>
                  </span>
                  {on && <Check className="absolute right-3 top-3 size-4 text-brand" strokeWidth={3} aria-hidden />}
                </label>
              );
            })}
          </div>
        </fieldset>

        {error && (
          <p role="alert" className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
            {error}
          </p>
        )}
        <button type="submit" disabled={!valid || busy} className="btn btn-primary btn-lg mt-8 w-full sm:w-auto">
          {busy ? "Opening…" : <>Enter workspace <ArrowRight className="btn-arrow size-4" aria-hidden /></>}
        </button>
        <p className="mt-4 text-xs text-muted-foreground">
          Demo workspace: anyone can pick any role. Everything you do is recorded under the name you choose.
        </p>
      </form>
    </main>
  );
}
