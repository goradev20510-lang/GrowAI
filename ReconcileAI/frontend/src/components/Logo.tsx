import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="font-display text-[18px] font-bold text-fg">
      ReconcileAI
    </Link>
  );
}
