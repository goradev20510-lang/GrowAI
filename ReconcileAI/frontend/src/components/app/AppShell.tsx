"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Command } from "cmdk";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { MagnifyingGlass, Play, Database, UserCircle } from "@phosphor-icons/react";
import { api, downloadReport } from "@/lib/api";
import { AccountButton } from "@/components/app/Auth";
import { useReviewer } from "@/components/providers";
import { Logo } from "@/components/Logo";
import { Button, inputCls } from "@/components/ui";

const NAV = [
  { href: "/app/overview", label: "Overview" },
  { href: "/app/review", label: "Review" },
  { href: "/app/credits", label: "Bank credits" },
  { href: "/app/import", label: "Import" },
  { href: "/app/reports", label: "Reports" },
  { href: "/app/audit", label: "Audit trail" },
  { href: "/app/ask", label: "Ask the data" },
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
      <header className="sticky top-0 z-40 border-b border-line bg-void/80 backdrop-blur-xl">
        <div className="shell flex h-16 items-center gap-6">
          <Logo href="/" />
          <nav className="-mx-2 flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto px-2 [scrollbar-width:none]" aria-label="Workspace">
            {NAV.map((n) => {
              const active = path?.startsWith(n.href);
              const count = n.href === "/app/review" ? s?.review_queue : undefined;
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                  className={clsx("relative flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13.5px] transition-colors duration-150",
                    active ? "text-fg" : "text-fg-3 hover:text-fg")}>
                  {active && (
                    <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-white/[0.08]"
                      transition={{ type: "spring", bounce: 0.15, duration: 0.45 }} />
                  )}
                  <span className="relative">{n.label}</span>
                  {!!count && <span className="num relative rounded-full bg-amber/15 px-1.5 text-[11.5px] text-amber">{count}</span>}
                </Link>
              );
            })}
          </nav>
          <button onClick={() => setCmd(true)}
            className="hidden h-9 shrink-0 cursor-pointer items-center gap-2 rounded-full border border-line-2 px-3 text-[13px] text-fg-3 transition-colors hover:border-line-3 hover:text-fg lg:flex">
            <MagnifyingGlass className="size-4" /> Go to <kbd className="font-mono text-[11px] text-fg-4">⌘K</kbd>
          </button>
          <AccountButton />
        </div>
        <div className="border-t border-line">
          <div className="shell flex flex-wrap items-center gap-3 py-2.5">
            <label className="flex items-center gap-2 text-[13px] text-fg-3">
              <UserCircle className="size-5" />
              <span className="sr-only">Reviewer</span>
              <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Reviewer name" title="Recorded against every approval, rejection and reassignment."
                className={clsx(inputCls, "h-8 w-[220px] rounded-full text-[13px]", !reviewer.trim() && "border-amber/40")} />
            </label>
            <span className="num ml-auto hidden text-[12.5px] text-fg-4 sm:block">
              {s ? `${s.total_transactions} credits · ${s.invoices_total} invoices` : ""}
            </span>
            <Button size="sm" variant="quiet" onClick={() => demo.mutate()} loading={demo.isPending}>
              {!demo.isPending && <Database className="size-4" />} Load demo data
            </Button>
            <Button size="sm" variant="primary" onClick={() => reconcile.mutate()} loading={reconcile.isPending}>
              {!reconcile.isPending && <Play weight="fill" className="size-3.5" />} Run reconciliation
            </Button>
          </div>
        </div>
      </header>
      <main className="shell pb-32 pt-10">{children}</main>
      <CommandBar open={cmd} setOpen={setCmd} onReconcile={() => reconcile.mutate()} onDemo={() => demo.mutate()} />
    </div>
  );
}

function CommandBar({ open, setOpen, onReconcile, onDemo }: {
  open: boolean; setOpen: (v: boolean) => void; onReconcile: () => void; onDemo: () => void;
}) {
  const router = useRouter();
  const go = (fn: () => void) => () => { setOpen(false); fn(); };
  const item = "flex h-11 cursor-pointer items-center rounded-xl px-3 text-[14px] text-fg-2 data-[selected=true]:bg-white/[0.07] data-[selected=true]:text-fg";
  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Go to"
      overlayClassName="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm"
      contentClassName="fixed left-1/2 top-[18vh] z-[61] w-[min(560px,92vw)] -translate-x-1/2 overflow-hidden rounded-2xl border border-line-2 bg-s2 shadow-[0_40px_80px_-20px_rgb(0_0_0/0.8)]">
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
