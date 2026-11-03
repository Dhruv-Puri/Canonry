"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

type Toast = { id: number; message: string };

const EVENT = "canonry:toast";
const SHOW_MS = 3600;

/** Confirm that an action worked. Callable from anywhere; the Toaster in the layout shows it. */
export function toast(message: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<string>(EVENT, { detail: message }));
}

/** Bottom-centre confirmations, announced politely to screen readers; at most three at once. */
export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  const next = useRef(1);

  useEffect(() => {
    const timers: number[] = [];
    const onToast = (e: Event) => {
      const message = (e as CustomEvent<string>).detail;
      if (!message) return;
      const id = next.current++;
      setItems((cur) => [...cur.filter((t) => t.message !== message), { id, message }].slice(-3));
      timers.push(window.setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), SHOW_MS));
    };
    window.addEventListener(EVENT, onToast);
    return () => {
      window.removeEventListener(EVENT, onToast);
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-20 z-[60] flex flex-col items-center gap-2 px-4"
    >
      {items.map((t) => (
        <div key={t.id} className="toast">
          <CheckCircle2 className="size-4 shrink-0 text-success-fg" aria-hidden />
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
