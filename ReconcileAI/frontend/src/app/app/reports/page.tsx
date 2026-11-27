"use client";

import clsx from "clsx";
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";
import { DownloadSimple } from "@phosphor-icons/react";
import { api, downloadReport, type Invoice, type TdsRow } from "@/lib/api";
import { fmtDate, inr, pct } from "@/lib/format";
import { AGEING_LABELS, TDS_STATUS, invStatus, txnStatus } from "@/lib/vocab";
import { useReviewer } from "@/components/providers";
import { Button, ErrorNote, Field, Mono, Notice, PageHead, Pills, SectionHead, Skeleton, Status, Table, inputCls } from "@/components/ui";

const TABS = ["Summary", "Receivables ageing", "Customers", "TDS register", "Invoices", "Export"];

export default function ReportsPage() {
  return (
    <>
      <PageHead title="Reports." lede="Ledger figures for month-end: where the cash went, what is still owed, how old it is, and which tax deductions still need evidence." />
      <Tabs.Root defaultValue={TABS[0]}>
        <Tabs.List className="flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]" aria-label="Report">
          {TABS.map((t) => (
            <Tabs.Trigger key={t} value={t}
              className="-mb-px shrink-0 cursor-pointer border-b border-transparent px-4 pb-3.5 pt-1 text-[14px] text-fg-3 transition-colors hover:text-fg data-[state=active]:border-fg data-[state=active]:text-fg">
              {t}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <div className="pt-10">
          <Tabs.Content value="Summary"><Summary /></Tabs.Content>
          <Tabs.Content value="Receivables ageing"><Ageing /></Tabs.Content>
          <Tabs.Content value="Customers"><Customers /></Tabs.Content>
          <Tabs.Content value="TDS register"><Tds /></Tabs.Content>
          <Tabs.Content value="Invoices"><Invoices /></Tabs.Content>
          <Tabs.Content value="Export"><Export /></Tabs.Content>
        </div>
      </Tabs.Root>
    </>
  );
}

function group<T>(rows: T[], key: (r: T) => string) {
  const m = new Map<string, T[]>();
  rows.forEach((r) => m.set(key(r), [...(m.get(key(r)) ?? []), r]));
  return [...m.entries()];
}

function Summary() {
  const s = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const t = useQuery({ queryKey: ["transactions"], queryFn: api.transactions });
  const i = useQuery({ queryKey: ["invoices"], queryFn: api.invoices });
  const draft = useMutation({ mutationFn: api.draftSummary, onError: (e) => toast.error((e as Error).message) });
  if (s.error) return <ErrorNote error={s.error} />;
  if (!s.data || !t.data || !i.data) return <Skeleton className="h-80" />;
  const total = s.data.total_transactions || 1;
  const byTxn = group(t.data, (x) => x.status).map(([k, r]) => ({ k, n: r.length, sum: r.reduce((a, x) => a + Number(x.credit_amount || 0), 0) }));
  const byInv = group(i.data, (x) => x.status).map(([k, r]) => ({ k, n: r.length,
    total: r.reduce((a, x) => a + Number(x.total_amount || 0), 0), out: r.reduce((a, x) => a + Number(x.outstanding_amount || 0), 0) }));
  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-3 text-[14px] font-medium">Bank credits by status</p>
          <Table rows={byTxn} rowKey={(r) => r.k} empty="No credits yet." cols={[
            { key: "s", head: "Status", cell: (r) => <Status {...txnStatus(r.k)} /> },
            { key: "n", head: "Credits", num: true, cell: (r) => r.n },
            { key: "a", head: "Amount", num: true, cell: (r) => inr(r.sum) },
          ]} />
        </div>
        <div>
          <p className="mb-3 text-[14px] font-medium">Invoices by status</p>
          <Table rows={byInv} rowKey={(r) => r.k} empty="No invoices yet." cols={[
            { key: "s", head: "Status", cell: (r) => <Status {...invStatus(r.k)} /> },
            { key: "n", head: "Invoices", num: true, cell: (r) => r.n },
            { key: "v", head: "Invoice value", num: true, cell: (r) => inr(r.total) },
            { key: "o", head: "Outstanding", num: true, cell: (r) => inr(r.out) },
          ]} />
        </div>
      </div>
      <div className="card mt-6 p-[clamp(22px,3vw,36px)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 className="text-[1.5rem]">Management summary.</h3>
            <p className="mt-1.5 text-[13px] text-fg-3">A draft written by the model from the figures above. Check every number against the tables before you send it.</p>
          </div>
          <Button onClick={() => draft.mutate()} loading={draft.isPending}>Draft summary</Button>
        </div>
        <p className="mt-6 max-w-[72ch] whitespace-pre-line text-[15px] leading-relaxed text-fg-2">
          {draft.data?.text ??
            `${s.data.total_transactions} credits processed, ${s.data.matched} matched (${pct(s.data.matched / total)}), ${s.data.needs_review} awaiting review and ${s.data.unmatched} unmatched. Outstanding receivables stand at ${inr(s.data.outstanding_value)}.`}
        </p>
        {draft.data && !draft.data.used_llm && <p className="mt-3 text-[12.5px] text-fg-4">Model unavailable, so this is the template summary.</p>}
      </div>
    </>
  );
}

function Ageing() {
  const q = useQuery({ queryKey: ["aging"], queryFn: api.aging });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-80" />;
  const { buckets, by_customer, detail, as_of } = q.data;
  if (!detail.length) return <Notice tone="ice">Nothing outstanding.</Notice>;
  const grand = buckets.reduce((a, b) => a + b.outstanding, 0) || 1;
  const max = Math.max(...buckets.map((b) => b.outstanding), 1);
  const labels = Object.values(AGEING_LABELS);
  return (
    <>
      <p className="mb-6 text-[13px] text-fg-3">Open and part-paid invoices as of {fmtDate(as_of)}. Days overdue = today minus due date.</p>
      <div className="card p-[clamp(22px,3vw,36px)]">
        {buckets.map((b, i) => (
          <div key={b.bucket} className="grid grid-cols-[minmax(130px,190px)_1fr_auto] items-center gap-5 border-b border-line py-4 last:border-b-0">
            <span className="text-[14px] text-fg-2">{AGEING_LABELS[b.bucket] ?? b.bucket}</span>
            <span className="h-2.5 overflow-hidden rounded-full bg-white/[0.05]">
              <motion.span className="block h-full origin-left rounded-full" style={{ width: `${(b.outstanding / max) * 100}%`,
                background: i === 0 ? "#bfd5dd" : i < 3 ? "#ffab00" : "#e8735f", opacity: 0.35 + 0.65 * (b.outstanding / max) }}
                initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }}
                transition={{ duration: 0.9, delay: i * 0.06, ease: [0.16, 1, 0.3, 1] }} />
            </span>
            <span className="num w-[190px] text-right text-[14px]">{inr(b.outstanding)} <span className="text-fg-4">· {b.invoices} · {pct(b.outstanding / grand)}</span></span>
          </div>
        ))}
      </div>
      <SectionHead title="By customer." />
      <Table rows={by_customer} rowKey={(r) => String(r.customer_name)} max={520} cols={[
        { key: "c", head: "Customer", cell: (r) => r.customer_name },
        ...Object.keys(AGEING_LABELS).map((k, i) => ({ key: k, head: labels[i].replace(" overdue", ""), num: true,
          cell: (r: Record<string, string | number | null>) => (Number(r[k]) ? inr(Number(r[k])) : <span className="text-fg-4">—</span>), className: "max-lg:hidden" })),
        { key: "t", head: "Total", num: true, cell: (r) => <b className="font-medium">{inr(Number(r.Total))}</b> },
      ]} />
      <SectionHead title={`Invoices · ${detail.length}`} />
      <Table rows={detail} rowKey={(r) => String(r.invoice_id)} max={520} cols={[
        { key: "i", head: "Invoice", cell: (r) => <Mono>{r.invoice_id}</Mono> },
        { key: "c", head: "Customer", cell: (r) => r.customer_name },
        { key: "d", head: "Due", cell: (r) => fmtDate(String(r.due_date)) },
        { key: "o", head: "Days overdue", num: true, cell: (r) => Math.max(0, Number(r.days_past_due) || 0) },
        { key: "a", head: "Outstanding", num: true, cell: (r) => inr(Number(r.outstanding_amount)) },
      ]} />
    </>
  );
}

function Customers() {
  const q = useQuery({ queryKey: ["customers"], queryFn: api.customers });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-80" />;
  return (
    <>
      <p className="mb-6 text-[13px] text-fg-3">Invoiced against what approved matches have applied. Received includes TDS the customer deducted.</p>
      <Table rows={q.data} rowKey={(r) => String(r.customer_name)} empty="No invoices yet." cols={[
        { key: "c", head: "Customer", cell: (r) => r.customer_name },
        { key: "n", head: "Invoices", num: true, cell: (r) => r.invoices, className: "max-md:hidden" },
        { key: "i", head: "Invoiced", num: true, cell: (r) => inr(Number(r.invoiced)) },
        { key: "r", head: "Received", num: true, cell: (r) => inr(Number(r.received)) },
        { key: "o", head: "Outstanding", num: true, cell: (r) => inr(Number(r.outstanding)) },
        { key: "p", head: "Open", num: true, cell: (r) => r.open_invoices, className: "max-md:hidden" },
        { key: "x", head: "Overpaid by", num: true, cell: (r) => (Number(r.overpaid_by) ? inr(Number(r.overpaid_by)) : <span className="text-fg-4">—</span>), className: "max-lg:hidden" },
      ]} />
    </>
  );
}

function Tds() {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const q = useQuery({ queryKey: ["tds"], queryFn: api.tds });
  const [picked, setPicked] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [cert, setCert] = useState<File | null>(null);
  const verify = useMutation({
    mutationFn: (id: string) => { const f = new FormData(); f.append("notes", note); if (cert) f.append("certificate", cert); return api.verifyTds(id, f); },
    onSuccess: () => { toast.success("TDS verified."); setNote(""); setCert(null); qc.invalidateQueries(); },
    onError: (e) => toast.error((e as Error).message),
  });
  const reject = useMutation({
    mutationFn: (id: string) => api.rejectTds(id, note.trim()),
    onSuccess: (r) => { toast.success(`TDS claim rejected. ${r.invoice_id ?? ""} now has ${inr(r.new_outstanding)} outstanding.`); setNote(""); qc.invalidateQueries(); },
    onError: (e) => toast.error((e as Error).message),
  });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-80" />;
  const rows = q.data;
  const sum = (f: (r: TdsRow) => boolean) => rows.filter(f).reduce((a, r) => a + Number(r.amount || 0), 0);
  const comp = rows.find((r) => r.component_id === picked);
  const done = comp && ["verified", "rejected"].includes(comp.tds_status ?? "");
  return (
    <>
      <p className="mb-6 max-w-[80ch] text-[13px] text-fg-3">TDS customers deducted on approved matches. The deduction only counts once the Form 16A (or 26AS entry) is checked; a rejected claim re-opens the invoice for that amount.</p>
      {!rows.length ? <Notice>No TDS deductions on approved matches yet.</Notice> : (
        <>
          <div className="card mb-6 grid divide-line sm:grid-cols-3 sm:divide-x">
            {[["Awaiting certificate", sum((r) => !["verified", "rejected"].includes(r.tds_status ?? "")), "text-amber"],
              ["Verified", sum((r) => r.tds_status === "verified"), "text-ice"], ["Rejected", sum((r) => r.tds_status === "rejected"), "text-brick"]].map(([l, v, c]) => (
              <div key={String(l)} className="border-b border-line px-7 py-6 last:border-b-0 sm:border-b-0">
                <p className="text-[13px] text-fg-3">{l}</p>
                <p className={clsx("num mt-2 font-display text-[1.9rem] tracking-[-0.04em]", String(c))}>{inr(Number(v))}</p>
              </div>
            ))}
          </div>
          <Table<TdsRow> rows={rows} rowKey={(r) => r.component_id} selected={picked} onRow={(r) => setPicked(r.component_id)} cols={[
            { key: "i", head: "Invoice", cell: (r) => <Mono>{r.invoice_id}</Mono> },
            { key: "c", head: "Customer", cell: (r) => r.customer_name, className: "max-md:hidden" },
            { key: "t", head: "TDS", num: true, cell: (r) => inr(r.amount) },
            { key: "s", head: "Section", cell: (r) => r.tds_section ?? "—" },
            { key: "st", head: "Status", cell: (r) => TDS_STATUS[r.tds_status ?? ""] ?? "Claimed" },
          ]} />
          {comp ? (
            <div className="card mt-5 p-7">
              <p className="font-medium">{inr(comp.amount)} TDS on {comp.invoice_id} <span className="text-fg-3">· {comp.customer_name} · section {comp.tds_section ?? "not stated"}</span></p>
              {done ? <p className="mt-2 text-[13px] text-fg-3">Already {TDS_STATUS[comp.tds_status ?? ""]?.toLowerCase()}.</p> : (
                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <Field label="Form 16A (optional)"><input type="file" onChange={(e) => setCert(e.target.files?.[0] ?? null)} className={clsx(inputCls, "pt-2 file:mr-3 file:rounded-full file:border-0 file:bg-white/10 file:px-3 file:py-0.5 file:text-fg")} /></Field>
                  <Field label="Note"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Matched 26AS entry for Q3" className={inputCls} /></Field>
                  <div className="flex gap-2.5 md:col-span-2">
                    <Button variant="primary" disabled={!reviewer.trim()} loading={verify.isPending} onClick={() => verify.mutate(comp.component_id)}>Mark verified</Button>
                    <Button variant="danger" disabled={!reviewer.trim()} loading={reject.isPending}
                      onClick={() => (note.trim() ? reject.mutate(comp.component_id) : toast.error("Add a note explaining why the claim is rejected."))}>Reject claim</Button>
                  </div>
                </div>
              )}
            </div>
          ) : <p className="mt-4 text-[13px] text-fg-4">Select a row to verify it against a certificate or reject the claim.</p>}
        </>
      )}
    </>
  );
}

function Invoices() {
  const q = useQuery({ queryKey: ["invoices"], queryFn: api.invoices });
  const [f, setF] = useState("all");
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-80" />;
  const statuses = ["open", "partially_paid", "settled", "overpaid"].filter((s) => q.data.some((i) => i.status === s));
  return (
    <>
      <div className="mb-5"><Pills value={f} onChange={setF} options={[{ value: "all", label: "All", count: q.data.length },
        ...statuses.map((s) => ({ value: s, label: invStatus(s).label, count: q.data.filter((i) => i.status === s).length }))]} /></div>
      <Table<Invoice> rows={q.data.filter((i) => f === "all" || i.status === f)} rowKey={(i) => i.invoice_id} max={620} empty="No invoices loaded." cols={[
        { key: "i", head: "Invoice", cell: (i) => <Mono>{i.invoice_id}</Mono> },
        { key: "c", head: "Customer", cell: (i) => i.customer_name },
        { key: "d", head: "Invoice date", cell: (i) => fmtDate(i.invoice_date), className: "max-lg:hidden" },
        { key: "u", head: "Due", cell: (i) => fmtDate(i.due_date), className: "max-md:hidden" },
        { key: "t", head: "Total", num: true, cell: (i) => inr(i.total_amount) },
        { key: "o", head: "Outstanding", num: true, cell: (i) => inr(i.outstanding_amount) },
        { key: "s", head: "Status", cell: (i) => <Status {...invStatus(i.status)} /> },
      ]} />
    </>
  );
}

function Export() {
  return (
    <div className="card grain relative flex flex-col items-start gap-6 overflow-hidden p-[clamp(28px,5vw,56px)]">
      <h3 className="max-w-[18ch] text-[clamp(1.8rem,3.4vw,2.8rem)]">One workbook for month-end.</h3>
      <p className="max-w-[60ch] text-fg-2">Summary, transactions, invoices, allocations, settlement components, review cases, ageing, customers, TDS register, remittances and the audit log.</p>
      <button type="button" onClick={() => { downloadReport().catch((e) => toast.error((e as Error).message)); }} className="cursor-pointer inline-flex h-13 items-center gap-2 rounded-full bg-fg px-7 text-[15px] font-medium text-black transition-colors hover:bg-white">
        <DownloadSimple weight="bold" className="size-4" /> Download Excel report
      </button>
    </div>
  );
}
