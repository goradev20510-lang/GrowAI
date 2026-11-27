"use client";

import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { api, type Txn } from "@/lib/api";
import { fmtDate, inr, pct } from "@/lib/format";
import { txnStatus } from "@/lib/vocab";
import { useReviewer } from "@/components/providers";
import { Button, ErrorNote, KV, Mono, PageHead, Pills, Skeleton, Status, Table, inputCls } from "@/components/ui";
import { EmptyLedger } from "@/components/app/EmptyLedger";

const ORDER = ["unmatched", "review", "matched", "duplicate", "excluded"];

export default function CreditsPage() {
  const q = useQuery({ queryKey: ["transactions"], queryFn: api.transactions });
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);

  const txns = useMemo(() => q.data ?? [], [q.data]);
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    txns.forEach((t) => (m[t.status] = (m[t.status] ?? 0) + 1));
    return m;
  }, [txns]);
  const rows = txns.filter((t) => (filter === "all" || t.status === filter) &&
    (!search || `${t.transaction_id} ${t.utr ?? ""} ${t.narration ?? ""}`.toLowerCase().includes(search.toLowerCase())));

  const head = <PageHead title="Bank credits" lede="Every credit line from imported statements, and the invoices each one was applied to." />;
  if (q.error) return <>{head}<ErrorNote error={q.error} /></>;
  if (!q.data) return <>{head}<Skeleton className="h-[520px]" /></>;
  if (!txns.length) return <>{head}<EmptyLedger title="No bank credits yet." body="Import a bank statement to see its credit lines here, or load the synthetic demo dataset." /></>;

  return (
    <>
      {head}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <Pills value={filter} onChange={(v) => { setFilter(v); setPicked(null); }}
          options={[{ value: "all", label: "All", count: txns.length },
            ...ORDER.filter((s) => counts[s]).map((s) => ({ value: s, label: txnStatus(s).label, count: counts[s] }))]} />
        <label className="relative w-full sm:w-[300px]">
          <MagnifyingGlass className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-4" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Transaction, UTR or narration"
            aria-label="Search credits" className={clsx(inputCls, "pl-10")} />
        </label>
      </div>
      <Table<Txn> rows={rows} rowKey={(t) => t.transaction_id} selected={picked} max={560}
        onRow={(t) => setPicked(picked === t.transaction_id ? null : t.transaction_id)} empty="No credits match this filter."
        cols={[
          { key: "d", head: "Value date", cell: (t) => <span className="text-fg-2">{fmtDate(t.transaction_date)}</span> },
          { key: "t", head: "Transaction", cell: (t) => <Mono>{t.transaction_id}</Mono> },
          { key: "n", head: "Narration", cell: (t) => <span className="line-clamp-1 max-w-[40ch] text-fg-2">{t.narration}</span>, className: "max-lg:hidden" },
          { key: "u", head: "UTR", cell: (t) => <Mono>{t.utr}</Mono>, className: "max-xl:hidden" },
          { key: "a", head: "Amount", num: true, cell: (t) => inr(t.credit_amount) },
          { key: "s", head: "Status", cell: (t) => <Status {...txnStatus(t.status)} /> },
        ]} />
      <AnimatePresence mode="wait">
        {picked ? (
          <motion.div key={picked} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }} className="mt-5">
            <Detail id={picked} />
          </motion.div>
        ) : (
          <p className="mt-4 text-[13px] text-fg-4">Select a row to see which invoices it was applied to and why.</p>
        )}
      </AnimatePresence>
    </>
  );
}

function Detail({ id }: { id: string }) {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const q = useQuery({ queryKey: ["txn", id], queryFn: () => api.transaction(id) });
  const [note, setNote] = useState("");
  const rec = useMutation({
    mutationFn: () => api.reconcileOne(id),
    onSuccess: (r) => { toast.success(`${id}: ${txnStatus(r.outcome).label}${r.invoice_id ? `, ${r.invoice_id}` : ""}`); qc.invalidateQueries(); },
    onError: (e) => toast.error(`Reconciliation failed: ${(e as Error).message}`),
  });
  const undo = useMutation({
    mutationFn: () => api.reverse(id, note.trim()),
    onSuccess: () => { toast.success(`Match on ${id} reversed.`); setNote(""); qc.invalidateQueries(); },
    onError: (e) => toast.error((e as Error).message),
  });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const { transaction: t, allocations } = q.data;
  const reason = allocations.at(-1)?.decision_reason;

  return (
    <div className="card grid gap-10 p-[clamp(22px,3vw,40px)] lg:grid-cols-[1fr_2fr]">
      <div>
        <div className="flex items-center gap-3"><Mono>{t.transaction_id}</Mono><Status {...txnStatus(t.status)} /></div>
        <p className="num mt-3 font-display text-[2.4rem] font-bold tracking-tight">{inr(t.credit_amount)}</p>
        <div className="mt-5"><KV rows={[["Value date", fmtDate(t.transaction_date)], ["Bank", t.bank_name], ["Account", t.account_number, true], ["UTR", t.utr, true], ["Narration", t.narration, true]]} /></div>
      </div>
      <div>
        <p className="mb-3 text-[14px] font-medium">Applied to</p>
        {allocations.length ? (
          <Table rows={allocations} rowKey={(a) => a.allocation_id} cols={[
            { key: "i", head: "Invoice", cell: (a) => <Mono>{a.invoice_id}</Mono> },
            { key: "b", head: "Bank credit", num: true, cell: (a) => inr(a.bank_credit) },
            { key: "t", head: "TDS", num: true, cell: (a) => (a.tds ? inr(a.tds) : "—") },
            { key: "a", head: "Applied", num: true, cell: (a) => inr(a.applied) },
            { key: "s", head: "Score", num: true, cell: (a) => pct(a.score) },
            { key: "st", head: "Status", cell: (a) => <span className="capitalize text-fg-2">{a.status}</span> },
          ]} />
        ) : <p className="text-[14px] text-fg-3">Not applied to any invoice yet.</p>}
        {reason && (
          <div className="mt-5">
            <p className="text-[12.5px] text-fg-4">Match explanation (may be model-written; the table above is authoritative)</p>
            <p className="mt-1.5 whitespace-pre-line text-[14px] leading-relaxed text-fg-2">{reason}</p>
          </div>
        )}
        <div className="mt-6 flex flex-wrap items-center gap-3">
          {t.status === "unmatched" && <Button variant="primary" onClick={() => rec.mutate()} loading={rec.isPending}>Reconcile this credit</Button>}
          {t.status === "matched" && (
            <>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason to undo, e.g. Customer says this paid INV-021"
                className={clsx(inputCls, "max-w-[360px] flex-1")} aria-label="Reason to undo the match" />
              <Button variant="danger" disabled={!reviewer.trim() || !note.trim()} loading={undo.isPending} onClick={() => undo.mutate()}
                title={reviewer.trim() ? undefined : "Enter your name in the reviewer field first."}>
                Undo this match
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
