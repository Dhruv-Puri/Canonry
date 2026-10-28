import { CircleAlert, TriangleAlert } from "lucide-react";
import { BrandMark } from "@/components/brand";

// The home-page "product shot": a draft gets scanned, phrases are marked,
// findings slide in with their sources, the copy is fixed and the approval
// seal stamps down. Pure CSS animation on one 9s loop (see globals.css).
// Decorative: the real flow is the form below it, so it is aria-hidden.

const CHIPS = [
  { d: "0s", icon: CircleAlert, tone: "text-danger-fg bg-danger-bg", label: "Outdated term", src: "Rule TERM-04" },
  { d: "0.35s", icon: TriangleAlert, tone: "text-warning-fg bg-warning-bg", label: "Unsupported claim", src: "Rule CLM-02" },
  { d: "0.7s", icon: CircleAlert, tone: "text-danger-fg bg-danger-bg", label: "Contradicted count", src: "Fact C-001" },
];

const mark = (d: string) => ({ "--d": d }) as React.CSSProperties;

export function HeroDemo() {
  return (
    <div aria-hidden className="relative mx-auto w-full max-w-[540px] select-none py-6">
      <div className="glow pointer-events-none absolute -inset-12 -z-10 rounded-[56px] blur-2xl" />

      {/* the draft */}
      <div className="animate-float relative flex min-h-[340px] flex-col overflow-hidden rounded-[30px] border border-border bg-card shadow-float">
        <div className="flex items-center gap-2 border-b border-border px-6 py-4">
          <span className="size-2.5 rounded-full bg-[#e8b4a0]" />
          <span className="size-2.5 rounded-full bg-[#ecd08f]" />
          <span className="size-2.5 rounded-full bg-[#b9cfa4]" />
          <span className="ml-3 text-xs font-semibold text-foreground">Launch post</span>
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">Social</span>
        </div>

        <div className="relative px-7 pt-6">
          <p className="demo-original font-serif text-[21px] leading-[1.65] text-foreground">
            Meet <span className="demo-mark" style={mark("0s")}>Quillmark Insights</span> 2.0,{" "}
            <span className="demo-mark" style={mark("0.35s")}>India’s #1</span> analytics platform, trusted by{" "}
            <span className="demo-mark" style={mark("0.7s")}>5,000+ teams</span>.
          </p>
          <p className="demo-fixed absolute inset-x-7 top-6 font-serif text-[21px] leading-[1.65] text-foreground">
            Meet <b className="font-semibold text-success-fg">Quillmark Pulse</b> 2.0, an analytics platform, trusted by{" "}
            <b className="font-semibold text-success-fg">2,300+ teams</b>.
          </p>
          <div className="mt-6 space-y-2.5">
            <div className="h-2.5 w-11/12 rounded-full bg-muted" />
            <div className="h-2.5 w-4/5 rounded-full bg-muted" />
            <div className="h-2.5 w-2/3 rounded-full bg-muted" />
          </div>
        </div>

        <div className="mt-auto flex items-center gap-3 border-t border-border bg-muted/50 px-6 py-3.5">
          <span className="grid size-7 place-items-center rounded-full bg-gradient-to-br from-brand to-primary text-[11px] font-bold text-primary-foreground">
            A
          </span>
          <span className="text-xs text-muted-foreground">Arjun · just now</span>
          <span className="relative ml-auto h-6 w-28">
            <span className="demo-original absolute inset-0 grid place-items-center rounded-full bg-warning-bg text-[11px] font-semibold text-warning-fg">
              3 issues found
            </span>
            <span className="demo-fixed absolute inset-0 grid place-items-center rounded-full bg-success-bg text-[11px] font-semibold text-success-fg">
              Approved
            </span>
          </span>
        </div>

        {/* scanning line */}
        <div className="demo-scan pointer-events-none absolute inset-x-0 h-20 -translate-y-1/2 bg-gradient-to-b from-transparent via-highlight/45 to-transparent" />

        {/* seal */}
        <div className="demo-seal absolute right-6 top-[150px] grid size-28 place-items-center rounded-full border-[3px] border-double border-success-fg/70 bg-success-bg/95 text-center shadow-card">
          <div>
            <BrandMark className="mx-auto size-8" />
            <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-success-fg">Signed</p>
          </div>
        </div>
      </div>

      {/* findings floating off the right edge */}
      <div className="absolute -right-3 top-[118px] hidden w-60 space-y-2.5 sm:block xl:-right-14">
        {CHIPS.map(({ d, icon: Icon, tone, label, src }) => (
          <div
            key={label}
            className="demo-chip flex items-center gap-3 rounded-2xl border border-border bg-card/95 p-3 shadow-float backdrop-blur"
            style={mark(d)}
          >
            <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${tone}`}>
              <Icon className="size-4" strokeWidth={2.25} />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-semibold text-foreground">{label}</span>
              <span className="block font-mono text-[11px] text-muted-foreground">{src}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
