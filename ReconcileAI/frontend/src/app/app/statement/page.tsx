"use client";

import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { api, type StatementLine } from "@/lib/api";
import { fmtDate, inr, pct } from "@/lib/format";
import { DEBIT_STATUS, txnStatus } from "@/lib/vocab";
import { useReviewer } from "@/components/providers";
import { Button, ErrorNote, KV, Mono, PageHead, Pills, Skeleton, Status, Table, inputCls } from "@/components/ui";
import { DebitPanel } from "@/components/app/DebitPanel";
import { EmptyLedger } from "@/components/app/EmptyLedger";

type Filter = "all" | "in" | "out" | "to_link" | "review" | "unmatched";

const FILTERS: { value: Filter; label: string; test: (t: StatementLine) => boolean }[] = [
  { value: "all", label: "All", test: () => true },
  { value: "in", label: "Money in", test: (t) => t.direction === "in" },
  { value: "out", label: "Money out", test: (t) => t.direction === "out" },
  { value: "to_link", label: "Payments to link", test: (t) => t.unlinked > 0 },
  { value: "review", label: "In review", test: (t) => t.status === "review" },
  { value: "unmatched", label: "Unmatched", test: (t) => t.status === "unmatched" },
];

const lineStatus = (t: StatementLine) => (t.direction === "out" ? DEBIT_STATUS[t.status] : txnStatus(t.status));

export default function StatementPage() {
  const q = useQuery({ queryKey: ["statement"], queryFn: api.statement });
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);

  const lines = useMemo(() => q.data ?? [], [q.data]);
  const active = FILTERS.find((f) => f.value === filter)!;
  const rows = lines.filter((t) => active.test(t) &&
    (!search || `${t.transaction_id} ${t.utr ?? ""} ${t.narration ?? ""} ${t.linked_to.join(" ")}`.toLowerCase().includes(search.toLowerCase())));
  const current = lines.find((t) => t.transaction_id === picked);

  const head = <PageHead title="Statement" lede="Every bank line, money in and money out, with the invoice or vendor bill it is linked to. Select a line to open it." />;
  if (q.error) return <>{head}<ErrorNote error={q.error} /></>;
  if (!q.data) return <>{head}<Skeleton className="h-[520px]" /></>;
  if (!lines.length) return <>{head}<EmptyLedger title="No bank lines yet" body="Import a bank statement to see it here, or load the synthetic demo dataset." /></>;

  return (
    <>
      {head}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Pills value={filter} onChange={(v) => { setFilter(v); setPicked(null); }}
          options={FILTERS.map((f) => ({ value: f.value, label: f.label, count: lines.filter(f.test).length }))} />
        <label className="relative w-full sm:w-[280px]">
          <MagnifyingGlass className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-4" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Narration, UTR, invoice or vendor"
            aria-label="Search statement" className={clsx(inputCls, "pl-10")} />
        </label>
      </div>
      {current && (
        <div key={current.transaction_id} ref={(el) => el?.scrollIntoView({ block: "nearest" })} className="mb-5 scroll-mt-20">
          {current.direction === "out" ? <DebitPanel key={current.transaction_id} id={current.transaction_id} />
            : <Detail key={current.transaction_id} id={current.transaction_id} />}
        </div>
      )}
      <Table<StatementLine> rows={rows} rowKey={(t) => t.transaction_id} selected={picked} max={620}
        onRow={(t) => setPicked(picked === t.transaction_id ? null : t.transaction_id)} empty="No lines match this filter."
        cols={[
          { key: "d", head: "Date", cell: (t) => <span className="whitespace-nowrap text-fg-2">{fmtDate(t.transaction_date)}</span> },
          { key: "n", head: "Narration", cell: (t) => (
            <><span className="line-clamp-1 max-w-[34ch]">{t.narration}</span><Mono>{t.transaction_id}</Mono></>) },
          { key: "in", head: "Money in", num: true, cell: (t) => (t.direction === "in" ? inr(t.credit_amount) : "") },
          { key: "out", head: "Money out", num: true, cell: (t) => (t.direction === "out" ? inr(t.debit_amount) : "") },
          { key: "l", head: "Linked to", cell: (t) => <span className="text-fg-2">{t.linked_to.join(", ") || "—"}</span>, className: "max-lg:hidden" },
          { key: "s", head: "Status", cell: (t) => <Status {...lineStatus(t)} /> },
        ]} />
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
