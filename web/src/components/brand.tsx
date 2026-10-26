// Canonry's small set of graphics. Pure SVG in currentColor / theme
// variables, so they follow light and dark mode with no extra assets.

/** The mark: a seal of eight petals around a check, i.e. "approved canon". */
export function BrandMark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <g fill="var(--brand)">
        {Array.from({ length: 8 }, (_, i) => (
          <ellipse key={i} cx="16" cy="6.2" rx="3.1" ry="5.6" transform={`rotate(${i * 45} 16 16)`} opacity={i % 2 ? 0.55 : 1} />
        ))}
      </g>
      <circle cx="16" cy="16" r="6.4" fill="var(--card)" />
      <path d="M13 16.2l2.1 2.1 4-4.4" fill="none" stroke="var(--brand)" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Empty state: a page with a highlighted phrase and a check seal. */
export function EmptyIllustration({ className = "h-28 w-auto" }: { className?: string }) {
  return (
    <svg viewBox="0 0 160 112" className={className} aria-hidden fill="none">
      <rect x="34" y="10" width="72" height="92" rx="8" fill="var(--card)" stroke="var(--border-strong)" />
      <rect x="46" y="26" width="40" height="5" rx="2.5" fill="var(--border-strong)" />
      <rect x="46" y="38" width="48" height="4" rx="2" fill="var(--border)" />
      <rect x="46" y="48" width="22" height="6" rx="2" fill="var(--highlight)" />
      <rect x="70" y="49" width="24" height="4" rx="2" fill="var(--border)" />
      <rect x="46" y="60" width="44" height="4" rx="2" fill="var(--border)" />
      <rect x="46" y="70" width="30" height="4" rx="2" fill="var(--border)" />
      <circle cx="108" cy="78" r="18" fill="var(--background)" stroke="var(--brand-highlight)" strokeWidth="1.5" />
      <path d="M100 78.5l5.5 5.5 10-11" stroke="var(--brand)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20 36h8M24 32v8M132 22h6M135 19v6" stroke="var(--brand-highlight)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Verification seal used on the Proof of Compliance page. */
export function SealGraphic({ ok, className = "size-16" }: { ok: boolean; className?: string }) {
  const tone = ok ? "var(--success-fg)" : "var(--danger-fg)";
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden fill="none">
      <circle cx="32" cy="32" r="29" stroke={tone} strokeOpacity="0.25" strokeWidth="2" strokeDasharray="3 4" />
      <circle cx="32" cy="32" r="22" fill={ok ? "var(--success-bg)" : "var(--danger-bg)"} stroke={tone} strokeWidth="1.5" />
      {ok ? (
        <path d="M23 32.5l6 6 12-13" stroke={tone} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M25 25l14 14M39 25L25 39" stroke={tone} strokeWidth="3" strokeLinecap="round" />
      )}
    </svg>
  );
}
