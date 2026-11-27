import Link from "next/link";

/** Wordmark: two interlocking rings, a credit meeting its invoice. */
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-2.5 font-display text-[17px] font-medium tracking-[-0.03em] text-fg">
      <svg viewBox="0 0 28 18" className="h-[18px] w-7 transition-transform duration-500 ease-[var(--ease-out-expo)] group-hover:rotate-[-8deg]" aria-hidden>
        <circle cx="9" cy="9" r="7.25" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="19" cy="9" r="7.25" fill="none" stroke="#bfd5dd" strokeWidth="1.6" />
      </svg>
      ReconcileAI
    </Link>
  );
}
