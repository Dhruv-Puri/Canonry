import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import { TopNav } from "@/components/top-nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Canonry — brand-governance review workspace",
  description:
    "Marketing content goes in, gets checked against approved rules, terms and facts, and issues come back explained with citations for a human to decide.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Suspense fallback={<div className="h-14 border-b border-border/60" />}>
          <TopNav />
        </Suspense>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-border/60 py-4 text-center text-xs text-muted-foreground">
          Canonry prototype · Quillmark Analytics demo workspace
        </footer>
      </body>
    </html>
  );
}
