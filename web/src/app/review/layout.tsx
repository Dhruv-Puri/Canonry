import type { Metadata } from "next";

export const metadata: Metadata = { title: "Review queue" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
