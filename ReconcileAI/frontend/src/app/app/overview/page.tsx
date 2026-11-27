"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type Txn } from "@/lib/api";
import { fmtDate, inr, pct } from "@/lib/format";
import { txnStatus } from "@/lib/vocab";
import { ErrorNote, Mono, PageHead, SectionHead, Skeleton, Status, Table } from "@/components/ui";
import { EmptyLedger } from "@/components/app/EmptyLedger";

export default function OverviewPage() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  const txns = useQuery({ queryKey: ["transactions"], queryFn: api.transactions });

  const head = <PageHead title="Overview" lede="Every figure is computed from the ledger; the model only reads documents." />;
  if (summary.error) return <>{head}<ErrorNote error={summary.error} /></>;
  if (!summary.data || !txns.data) return <>{head}<Skeleton className="h-80" /></>;
  const s = summary.data;
  if (!txns.data.length)
    return <>{head}<EmptyLedger title="No bank credits yet" body="Import a bank statement and invoices, or load the synthetic demo dataset to walk through the workflow end to end." /></>;

  const total = s.amount_received || 0;
  const parts = [
    { key: "matched", amount: s.amount_matched, count: s.matched },
    { key: "review", amount: s.amount_in_review, count: s.needs_review },
    { key: "unmatched", amount: s.amount_unmatched, count: s.unmatched },
    { key: "duplicate", amount: s.amount_duplicate, count: s.duplicates },
  ];

  return (
    <>
      {head}
      <Table rows={parts} rowKey={(p) => p.key} cols={[
        { key: "s", head: "Status", cell: (p) => <Status {...txnStatus(p.key)} /> },
        { key: "n", head: "Credits", num: true, cell: (p) => p.count },
        { key: "a", head: "Amount", num: true, cell: (p) => inr(p.amount) },
        { key: "p", head: "Share", num: true, cell: (p) => pct(total ? p.amount / total : 0) },
      ]} />
      <p className="mt-3 text-[14px] text-fg-3">
        {s.invoices_open} invoices open, {s.invoices_partial} part-paid, {s.invoices_settled} settled.
      </p>

      <SectionHead title="Latest bank credits"
        aside={<Link href="/app/statement" className="text-[14px] text-fg-2 underline hover:text-fg">Full statement</Link>} />
      <Table<Txn> rows={txns.data.filter((t) => t.credit_amount > 0).slice(0, 8)} rowKey={(t) => t.transaction_id} cols={[
        { key: "d", head: "Value date", cell: (t) => <span className="text-fg-2">{fmtDate(t.transaction_date)}</span> },
        { key: "t", head: "Transaction", cell: (t) => <Mono>{t.transaction_id}</Mono> },
        { key: "n", head: "Narration", cell: (t) => <span className="line-clamp-1 max-w-[38ch] text-fg-2">{t.narration}</span>, className: "max-lg:hidden" },
        { key: "a", head: "Amount", num: true, cell: (t) => inr(t.credit_amount) },
        { key: "s", head: "Status", cell: (t) => <Status {...txnStatus(t.status)} /> },
      ]} />
    </>
  );
}
