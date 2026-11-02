import type { Metadata } from "next";

export const metadata: Metadata = { title: "My work" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
