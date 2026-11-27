"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { ArrowRight } from "@phosphor-icons/react";
import { api, type Case, type Txn } from "@/lib/api";
import { fmtDate, inr, inrShort, pct } from "@/lib/format";
import { excLabel, txnStatus } from "@/lib/vocab";
import { ErrorNote, Mono, PageHead, SectionHead, Skeleton, Status, Table, toneColor } from "@/components/ui";
import { Scene } from "@/components/three/Scene";
import { EmptyLedger } from "@/components/app/EmptyLedger";

export default function OverviewPage() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const txns = useQuery({ queryKey: ["transactions"], queryFn: api.transactions });
  const queue = useQuery({ queryKey: ["review"], queryFn: api.review });

  const head = (
    <PageHead title="Overview." lede="Bank credits matched against open receivables. Every figure is computed from the ledger; the model only reads documents." />
  );
  if (summary.error) return <>{head}<ErrorNote error={summary.error} /></>;
  if (!summary.data || !txns.data) return <>{head}<Skeleton className="h-[420px]" /></>;
  const s = summary.data;
  if (!txns.data.length)
    return <>{head}<EmptyLedger title="No bank credits yet." body="Import a bank statement and invoices, or load the synthetic demo dataset to walk through the workflow end to end." /></>;

  const total = s.amount_received || 0;
  const parts = [
    { key: "matched", amount: s.amount_matched, count: s.matched },
    { key: "review", amount: s.amount_in_review, count: s.needs_review },
    { key: "unmatched", amount: s.amount_unmatched, count: s.unmatched },
    { key: "duplicate", amount: s.amount_duplicate, count: s.duplicates },
  ];
  const side = [
    { label: "Outstanding receivables", value: inrShort(s.outstanding_value), note: `${inr(s.outstanding_value)} across open and part-paid invoices` },
    { label: "Open invoices", value: String(s.invoices_open + s.invoices_partial), note: `${s.invoices_open} open, ${s.invoices_partial} part-paid, ${s.invoices_settled} settled` },
    { label: "TDS awaiting certificate", value: inrShort(s.tds_pending), note: "Deducted on approved matches, Form 16A not yet checked" },
  ];

  const top = (queue.data ?? []).slice(0, 5);
  const latest = txns.data.slice(0, 8);

  return (
    <>
      {head}
      <section className="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
        <div className="card relative overflow-hidden p-[clamp(24px,3.4vw,44px)]">
          <Scene compact effects={false} className="pointer-events-none absolute -right-24 -top-24 size-[440px] opacity-60 max-sm:hidden" />
          <p className="relative text-[14px] text-fg-3">Bank credits received</p>
          <p className="num relative mt-3 font-display text-[clamp(2.8rem,6.4vw,5.4rem)] font-medium leading-none tracking-[-0.05em]">
            {inr(total, 0)}
          </p>
          <p className="relative mt-3 text-[14px] text-fg-3">{s.total_transactions} credit lines from imported statements</p>

          <div className="relative mt-10 flex h-3 gap-[3px] overflow-hidden rounded-full" role="img"
            aria-label={`Share of value: ${parts.map((p) => `${txnStatus(p.key).label} ${pct(total ? p.amount / total : 0)}`).join(", ")}`}>
            {parts.filter((p) => p.amount > 0).map((p, i) => (
              <motion.span key={p.key} className="h-full origin-left rounded-[2px]"
                style={{ flex: `${p.amount} 1 0`, background: toneColor[txnStatus(p.key).tone] }}
                initial={{ scaleX: 0 }} animate={{ scaleX: 1 }}
                transition={{ duration: 1, delay: 0.1 + i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                title={`${txnStatus(p.key).label}: ${inr(p.amount)}`} />
            ))}
          </div>

          <table className="relative mt-8 w-full text-[14px]">
            <thead>
              <tr className="text-[12px] text-fg-4">
                <th className="pb-2 text-left font-medium">Status</th>
                <th className="pb-2 text-right font-medium">Credits</th>
                <th className="pb-2 text-right font-medium">Amount</th>
                <th className="pb-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {parts.map((p) => {
                const st = txnStatus(p.key);
                return (
                  <tr key={p.key} className="border-t border-line">
                    <td className="py-2.5"><Status label={st.label} tone={st.tone} /></td>
                    <td className="num py-2.5 text-right text-fg-2">{p.count}</td>
                    <td className="num py-2.5 text-right">{inr(p.amount)}</td>
                    <td className="num py-2.5 text-right text-fg-3">{pct(total ? p.amount / total : 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col gap-4">
          <Link href="/app/review" className="card group flex flex-col justify-between gap-6 p-7 transition-colors hover:border-line-3">
            <div className="flex items-start justify-between">
              <p className="text-[14px] text-fg-3">Credits waiting for a reviewer</p>
              <ArrowRight className="size-5 text-fg-3 transition-transform duration-300 group-hover:translate-x-1 group-hover:text-fg" />
            </div>
            <p className="num font-display text-[clamp(3rem,5vw,4.2rem)] leading-none tracking-[-0.05em] text-amber">{s.review_queue}</p>
          </Link>
          <div className="card flex-1 px-7 py-2">
            {side.map((k) => (
              <div key={k.label} className="border-b border-line py-5 last:border-b-0">
                <div className="flex items-baseline justify-between gap-4">
                  <p className="text-[14px] text-fg-2">{k.label}</p>
                  <p className="num font-display text-[1.6rem] tracking-[-0.03em]">{k.value}</p>
                </div>
                <p className="mt-1 text-[12.5px] text-fg-4">{k.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {top.length > 0 && (
        <>
          <SectionHead title="Largest credits waiting for review." aside={<MoreLink href="/app/review">Open the queue</MoreLink>} />
          <Table<Case> rows={top} rowKey={(c) => c.case_id} cols={[
            { key: "t", head: "Transaction", cell: (c) => <Mono>{c.transaction_id}</Mono> },
            { key: "r", head: "Reason", cell: (c) => excLabel(c.exception_type) },
            { key: "i", head: "Suggested invoice", cell: (c) => <Mono>{c.invoice_id ?? "—"}</Mono>, className: "max-md:hidden" },
            { key: "a", head: "Amount", num: true, cell: (c) => inr(c.amount) },
          ]} />
        </>
      )}

      <SectionHead title="Latest bank credits." aside={<MoreLink href="/app/credits">All credits</MoreLink>} />
      <Table<Txn> rows={latest} rowKey={(t) => t.transaction_id} cols={[
        { key: "d", head: "Value date", cell: (t) => <span className="text-fg-2">{fmtDate(t.transaction_date)}</span> },
        { key: "t", head: "Transaction", cell: (t) => <Mono>{t.transaction_id}</Mono> },
        { key: "n", head: "Narration", cell: (t) => <span className="line-clamp-1 max-w-[38ch] text-fg-2">{t.narration}</span>, className: "max-lg:hidden" },
        { key: "a", head: "Amount", num: true, cell: (t) => inr(t.credit_amount) },
        { key: "s", head: "Status", cell: (t) => <Status {...txnStatus(t.status)} /> },
      ]} />
    </>
  );
}

function MoreLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-1.5 text-[14px] text-fg-2 transition-colors hover:text-fg">
      {children}
      <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5" />
    </Link>
  );
}
