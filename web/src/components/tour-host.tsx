"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ProductTour } from "@/components/tour";
import { useIdentity } from "@/components/identity";
import { wantsGuide } from "@/components/guide";
import { roleHome, type Role } from "@/lib/roles";

/** The roles whose tour this browser has already seen, e.g. ["creator","reviewer"]. */
const SEEN_KEY = "canonry.tour.seen";

function seenRoles(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function markSeen(role: string) {
  try {
    const seen = seenRoles();
    if (!seen.includes(role)) window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen, role]));
  } catch {
    // storage blocked: the tour may show again next visit, never twice in one
  }
}

/**
 * Owns the product tour for the whole app. A guided visitor sees it once for each profile they
 * try, with one step for every window that profile has, so no workspace is missed.
 */
export function TourHost() {
  const { me } = useIdentity();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  // Once per role, only for visitors who asked to be shown around: the first time they arrive as a
  // creator, a reviewer, an agency partner or an admin. Never again after that, in any session;
  // "Take the tour" on the home page still opens it on demand.
  useEffect(() => {
    if (!me) return;
    if (wantsGuide() && !seenRoles().includes(me.role)) setOpen(true);
  }, [me]);

  // One walkthrough at a time: while the tour is open, the step-by-step guide and its pointer
  // step aside (they sat on top of each other, and the guide's next step was hidden behind it).
  useEffect(() => {
    document.body.classList.toggle("tour-open", open);
    return () => document.body.classList.remove("tour-open");
  }, [open]);

  // The home page's "Take the tour" button asks this host to open it.
  useEffect(() => {
    const openTour = () => setOpen(true);
    window.addEventListener("canonry:open-tour", openTour);
    return () => window.removeEventListener("canonry:open-tour", openTour);
  }, []);

  function close() {
    setOpen(false);
    if (me) markSeen(me.role);
  }

  function finish() {
    close();
    if (!me) return;
    router.push(roleHome(me.role));
    window.setTimeout(() => {
      document.getElementById("check")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 400);
  }

  if (!me) return null;
  return <ProductTour open={open} role={me.role as Role} onClose={close} onFinish={finish} />;
}