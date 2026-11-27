"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, type VendorBill } from "@/lib/api";
import { fmtDate, inr } from "@/lib/format";
import { BILL_STATUS } from "@/lib/vocab";
import { useReviewer } from "@/components/providers";
import { ErrorNote, LinkButton, Mono, PageHead, SectionHead, Skeleton, Status, Table } from "@/components/ui";

export default function VendorsPage() {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const q = useQuery({ queryKey: ["vendorBills"], queryFn: api.vendorBills });
  const [picked, setPicked] = useState<string | null>(null);
  const onFile = useMutation({
    mutationFn: (b: VendorBill) => api.billOnFile(b.bill_id, !b.bill_on_file),
    onSuccess: () => qc.invalidateQueries(),
    onError: (e) => toast.error((e as Error).message),
  });

  const head = <PageHead title="Vendors" lede="Bills to be paid, and the bank payments linked to each one. Link payments from the Statement tab."
    actions={<LinkButton href="/app/statement" size="sm">Open statement</LinkButton>} />;
  if (q.error) return <>{head}<ErrorNote error={q.error} /></>;
  if (!q.data) return <>{head}<Skeleton className="h-80" /></>;
  const current = q.data.find((b) => b.bill_id === picked);

  return (
    <>
      {head}
      <Table<VendorBill> rows={q.data} rowKey={(b) => b.bill_id} selected={picked}
        onRow={(b) => setPicked(picked === b.bill_id ? null : b.bill_id)}
        empty="No vendor bills yet. Import a bill register, or load the demo data."
        cols={[
          { key: "v", head: "Vendor", cell: (b) => <><p className="font-bold">{b.vendor_name}</p><Mono>{b.bill_number}</Mono></> },
          { key: "a", head: "Bill", num: true, cell: (b) => inr(b.amount) },
          { key: "p", head: "Paid", num: true, cell: (b) => inr(b.paid) },
          { key: "n", head: "Pending", num: true, cell: (b) => <b>{inr(b.pending)}</b> },
          { key: "s", head: "Status", cell: (b) => <Status {...BILL_STATUS[b.status]} /> },
          { key: "f", head: "Papers for audit", cell: (b) => (
            <label className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={b.bill_on_file} disabled={!reviewer.trim() || onFile.isPending}
                title={reviewer.trim() ? undefined : "Enter your name in the reviewer field first."}
                onChange={() => onFile.mutate(b)} className="size-4 accent-[var(--color-ice)]" />
              Bill on file
            </label>) },
        ]} />
      {current && (
        <>
          <SectionHead title={`Payments for ${current.vendor_name} · ${current.bill_number}`} />
          <p className="mb-3 text-[13px] text-fg-3">Bill date {fmtDate(current.bill_date)} · due {fmtDate(current.due_date)}</p>
          <Table rows={current.payments} rowKey={(p) => p.payment_id} empty="No payment is linked to this bill yet." cols={[
            { key: "d", head: "Paid on", cell: (p) => fmtDate(p.transaction_date) },
            { key: "t", head: "Bank line", cell: (p) => <Mono>{p.transaction_id}</Mono> },
            { key: "w", head: "Linked by", cell: (p) => p.linked_by },
            { key: "a", head: "Amount", num: true, cell: (p) => inr(p.amount) },
          ]} />
          <p className="mt-3 text-[13px] text-fg-3">To undo a link, open the bank line on the <Link href="/app/statement" className="underline">Statement</Link> tab.</p>
        </>
      )}
    </>
  );
}
