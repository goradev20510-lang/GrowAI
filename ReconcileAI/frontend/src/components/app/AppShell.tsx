"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, downloadReport } from "@/lib/api";
import { AccountButton } from "@/components/app/Auth";
import { useReviewer } from "@/components/providers";
import { HeroStats } from "@/components/app/HeroStats";
import { Button } from "@/components/ui";

const NAV = [
  { href: "/app/review", label: "Needs review" },
  { href: "/app/overview", label: "Overview" },
  { href: "/app/credits", label: "Bank credits" },
  { href: "/app/import", label: "Import" },
  { href: "/app/reports", label: "Reports" },
  { href: "/app/audit", label: "Activity" },
  { href: "/app/ask", label: "Ask" },
];

export function useBatchActions() {
  const qc = useQueryClient();
  const reconcile = useMutation({
    mutationFn: api.reconcile,
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.success(r.total
        ? `${r.total} credits processed: ${r.matched} matched, ${r.needs_review} to review, ${r.unmatched} unmatched, ${r.duplicates ?? 0} duplicates.`
        : "Nothing to reconcile. There are no unmatched credits.");
    },
    onError: (e) => toast.error(`Reconciliation stopped: ${(e as Error).message}`),
  });
  const demo = useMutation({
    mutationFn: api.loadDemo,
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.success(r.already_loaded ? "The demo dataset is already loaded."
        : `Loaded ${r.invoices} invoices and ${r.transactions} bank credits (synthetic).`);
    },
    onError: (e) => toast.error(`Could not load the demo dataset: ${(e as Error).message}`),
  });
  return { reconcile, demo };
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data: s } = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const { reviewer, setReviewer } = useReviewer();
  const { reconcile, demo } = useBatchActions();
  const [cmd, setCmd] = useState(false);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmd((v) => !v); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  return (
    <div className="min-h-dvh">
      <header className="bg-hero">
        <div className="shell pb-10 pt-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-[2.4rem]"><Link href="/">ReconcileAI</Link></h1>
              <p className="mt-1 max-w-[60ch] text-[16px] text-fg-2">
                Bank money in, matched to open invoices and checked line by line against the bank statement.
              </p>
            </div>
            <AccountButton />
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2.5">
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name (reviewer)"
              aria-label="Reviewer name" title="Recorded against every approval, rejection and reassignment."
              className={clsx("h-10 w-[210px] rounded-full border bg-transparent px-4 text-[14px] text-fg placeholder:text-fg-3",
                reviewer.trim() ? "border-line-3" : "border-amber/60")} />
            <Button variant="primary" onClick={() => reconcile.mutate()} loading={reconcile.isPending}>Run reconciliation</Button>
            <Button onClick={() => demo.mutate()} loading={demo.isPending}>Load demo data</Button>
          </div>
          <HeroStats />
        </div>
      </header>
      <nav className="sticky top-0 z-40 border-b border-line bg-void" aria-label="Workspace">
        <div className="shell flex gap-1 overflow-x-auto [scrollbar-width:none]">
          {NAV.map((n) => {
            const active = path?.startsWith(n.href);
            const count = n.href === "/app/review" ? s?.review_queue : undefined;
            return (
              <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                className={clsx("flex h-14 shrink-0 items-center gap-2 border-b-[3px] px-3.5 text-[15px] font-bold transition-colors",
                  active ? "border-brick text-fg" : "border-transparent text-fg-3 hover:text-fg")}>
                {n.label}
                {!!count && <span className="num grid h-6 min-w-6 place-items-center rounded-full bg-brick px-1.5 text-[12px] text-white">{count}</span>}
              </Link>
            );
          })}
        </div>
      </nav>
      <main className="shell pb-24 pt-8">{children}</main>
      <CommandBar open={cmd} setOpen={setCmd} onReconcile={() => reconcile.mutate()} onDemo={() => demo.mutate()} />
    </div>
  );
}

function CommandBar({ open, setOpen, onReconcile, onDemo }: {
  open: boolean; setOpen: (v: boolean) => void; onReconcile: () => void; onDemo: () => void;
}) {
  const router = useRouter();
  const go = (fn: () => void) => () => { setOpen(false); fn(); };
  const item = "flex h-11 cursor-pointer items-center rounded-md px-3 text-[14px] text-fg-2 data-[selected=true]:bg-white/[0.07] data-[selected=true]:text-fg";
  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Go to"
      overlayClassName="fixed inset-0 z-[60] bg-black/60"
      contentClassName="fixed left-1/2 top-[18vh] z-[61] w-[min(560px,92vw)] -translate-x-1/2 overflow-hidden rounded-lg border border-line-2 bg-s2">
      <Command.Input placeholder="Jump to a page or run an action" className="h-14 w-full border-b border-line bg-transparent px-5 text-[15px] text-fg placeholder:text-fg-4 focus:outline-none" />
      <Command.List className="max-h-[50vh] overflow-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-[14px] text-fg-3">No match.</Command.Empty>
        <Command.Group heading="Pages" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[12px] [&_[cmdk-group-heading]]:text-fg-4">
          {NAV.map((n) => <Command.Item key={n.href} className={item} onSelect={go(() => router.push(n.href))}>{n.label}</Command.Item>)}
        </Command.Group>
        <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[12px] [&_[cmdk-group-heading]]:text-fg-4">
          <Command.Item className={item} onSelect={go(onReconcile)}>Run reconciliation</Command.Item>
          <Command.Item className={item} onSelect={go(onDemo)}>Load demo dataset</Command.Item>
          <Command.Item className={item} onSelect={go(() => { downloadReport().catch((e) => toast.error((e as Error).message)); })}>Download Excel report</Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
