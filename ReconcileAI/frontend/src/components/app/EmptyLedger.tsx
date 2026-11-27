"use client";

import Link from "next/link";
import { Scene } from "@/components/three/Scene";
import { Button } from "@/components/ui";
import { useBatchActions } from "./AppShell";

export function EmptyLedger({ title, body }: { title: string; body: string }) {
  const { demo } = useBatchActions();
  return (
    <section className="card relative grid min-h-[420px] overflow-hidden md:grid-cols-[1.1fr_1fr]">
      <div className="relative z-10 flex flex-col justify-center gap-6 p-[clamp(28px,5vw,56px)]">
        <h2 className="text-[clamp(1.8rem,3.4vw,2.8rem)]">{title}</h2>
        <p className="max-w-[46ch] text-fg-2">{body}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="primary" arrow onClick={() => demo.mutate()} loading={demo.isPending}>Load the demo dataset</Button>
          <Link href="/app/import" className="inline-flex h-10 items-center rounded-full border border-line-2 px-5 text-sm font-medium transition-colors hover:border-line-3 hover:bg-white/[0.04]">
            Import documents
          </Link>
        </div>
        <p className="text-[12.5px] text-fg-4">Synthetic invoices, bank credits and payment emails. No real client data.</p>
      </div>
      <Scene compact effects={false} className="pointer-events-none absolute inset-0 opacity-50 md:relative md:opacity-100" />
    </section>
  );
}
