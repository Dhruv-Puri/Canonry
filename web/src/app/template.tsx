// Re-mounted on every navigation (see Next's template.js), so each page
// settles in with the same soft rise instead of popping.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
