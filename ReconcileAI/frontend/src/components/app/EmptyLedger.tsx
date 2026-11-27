"use client";

import { Button, LinkButton } from "@/components/ui";
import { useBatchActions } from "./AppShell";
import { useCanLoadDemo } from "./Auth";

export function EmptyLedger({ title, body }: { title: string; body: string }) {
  const { demo } = useBatchActions();
  const canLoadDemo = useCanLoadDemo();
  return (
    <section className="border-y border-line py-12">
      <h2 className="text-[1.35rem]">{title}</h2>
      <p className="mt-2 max-w-[56ch] text-fg-2">{body}</p>
      <div className="mt-5 flex flex-wrap gap-2.5">
        {canLoadDemo && (
          <Button variant="primary" onClick={() => demo.mutate()} loading={demo.isPending}>Load the demo dataset</Button>
        )}
        <LinkButton href="/app/import">Import documents</LinkButton>
      </div>
      <p className="mt-4 text-[13px] text-fg-4">Synthetic invoices, bank credits and payment emails. No real client data.</p>
    </section>
  );
}
