import type { Metadata } from "next";
import { Suspense } from "react";
import { EB_Garamond, Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import { SiteNav } from "@/components/site-nav";
import { BrandMark } from "@/components/brand";
import { Spotlight } from "@/components/effects";
import { IdentityGate } from "@/components/identity";
import { GuidePanel, GuideProvider } from "@/components/guide";
import { TourHost } from "@/components/tour-host";
import { Toaster } from "@/components/toast";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Serif is reserved for the copy under review, so drafts read like print.
// Garamond for the tutorial's spoken lines: a warm book face that reads easily at a glance.
const garamond = EB_Garamond({
  variable: "--font-garamond",
  subsets: ["latin"],
});

const serif = Source_Serif_4({
  variable: "--font-serif-face",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "Canonry — brand-governance review workspace", template: "%s · Canonry" },
  description:
    "Marketing content goes in, gets checked against approved rules, terms and facts, and issues come back explained with citations for a human to decide.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${serif.variable} ${garamond.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col overflow-x-clip">
        <div aria-hidden className="scroll-progress" />
        <Spotlight />
        {/* the gate reads the URL (public routes skip sign-in), so it streams in */}
        <Suspense fallback={<div className="min-h-dvh" aria-busy="true" />}>
        <GuideProvider>
        <IdentityGate>
        <Suspense fallback={<div className="h-[68px]" />}>
          <SiteNav />
        </Suspense>
        <main className="mx-auto w-full max-w-6xl flex-1 px-5 pb-20 pt-8 sm:px-8 md:pt-12">{children}</main>
        <footer className="border-t border-border">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-5 py-6 text-xs text-muted-foreground sm:px-8">
            <BrandMark className="size-5" />
            <span className="font-semibold text-foreground">Canonry</span>
            <span>Brand governance for Quillmark Analytics · demo workspace, shared accounts on purpose</span>
            <span className="ml-auto">Every decision stays with a person.</span>
          </div>
        </footer>
        <GuidePanel />
        <TourHost />
        <Toaster />
        </IdentityGate>
        </GuideProvider>
        </Suspense>
      </body>
    </html>
  );
}
