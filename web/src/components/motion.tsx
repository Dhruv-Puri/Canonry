"use client";

import { useEffect, useRef, useState } from "react";

function useInView<T extends Element>() {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, inView] as const;
}

/** Lifts its children slightly the first time they scroll into view. They are never hidden (no opacity change). */
export function Reveal({
  children,
  delay = 0,
  className = "",
  as: Tag = "div",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "li";
}) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <Tag
      ref={ref as React.Ref<never>}
      className={`reveal ${inView ? "is-visible" : ""} ${className}`}
      style={{ "--reveal-delay": `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </Tag>
  );
}

/** Shows `value`; counts up to it from 0 when it scrolls into view (not under reduced motion). */
export function CountUp({ value, duration = 1200 }: { value: number; duration?: number }) {
  const [ref, inView] = useInView<HTMLSpanElement>();
  // the real number from the start, so a page that is never scrolled (or captured) never reads "0"
  const [shown, setShown] = useState(value);
  useEffect(() => {
    if (!inView) {
      setShown(value);
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setShown(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Background tabs throttle rAF; make sure the real number always lands.
    const done = window.setTimeout(() => setShown(value), duration + 150);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(done);
    };
  }, [inView, value, duration]);
  return (
    <span ref={ref} className="tabular-nums">
      {shown}
    </span>
  );
}
