"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ProductTour } from "@/components/tour";
import { useIdentity } from "@/components/identity";
import { wantsGuide } from "@/components/guide";
import { roleHome, type Role } from "@/lib/roles";

/** "1" once the tour has been closed, so a returning visitor is not interrupted. */
const SEEN_KEY = "canonry.tour.v1";
/** The role the tour last ran for, kept per tab so a role switch is noticed even after a remount. */
const ROLE_KEY = "canonry.tour.role";

/**
 * Owns the product tour for the whole app. It opens the first time a guided
 * visitor arrives, and again whenever they switch profile, with one step for
 * every window that profile has — so no workspace is missed.
 */
export function TourHost() {
  const { me } = useIdentity();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!me) return;
    let last: string | null = null;
    try {
      last = window.sessionStorage.getItem(ROLE_KEY);
    } catch {
      // storage blocked: still run the tour once for this mount
    }
    // A new browser session starts at the welcome screen, so it gets the tour
    // again; inside one session only a profile switch re-opens it.
    // Only for visitors who asked to be shown around: a returning visitor is never interrupted
    // (they can still press "Take the tour"). Before, any role switch opened it for everyone.
    if (wantsGuide() && (last === null || last !== me.role)) setOpen(true);
    try {
      window.sessionStorage.setItem(ROLE_KEY, me.role);
    } catch {
      // ignore
    }
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
    try {
      window.localStorage.setItem(SEEN_KEY, "1");
    } catch {
      // ignore
    }
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