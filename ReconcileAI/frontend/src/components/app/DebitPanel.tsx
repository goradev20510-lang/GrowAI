"use client";

import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, type VendorPayment } from "@/lib/api";
import { fmtDate, inr } from "@/lib/format";
import { useReviewer } from "@/components/providers";
import { Button, ErrorNote, KV, Mono, Skeleton, inputCls } from "@/components/ui";

/** One outgoing payment: what it is linked to, what could explain the rest, and undo. */
export function DebitPanel({ id }: { id: string }) {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const who = reviewer.trim();
  const q = useQuery({ queryKey: ["debit", id], queryFn: () => api.debit(id) });
  const bills = useQuery({ queryKey: ["vendorBills"], queryFn: api.vendorBills });
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");

  const done = (message: string) => { toast.success(message); setNote(""); setChoice(""); qc.invalidateQueries(); };
  const fail = (e: Error) => toast.error(e.message);
  const link = useMutation({ mutationFn: (bill: string) => api.linkDebit(id, bill), onSuccess: (r) => done(`${inr(r.amount)} linked.`), onError: fail });
  const other = useMutation({ mutationFn: () => api.notVendor(id, note.trim()), onSuccess: () => done("Marked as not a vendor payment."), onError: fail });

  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-64" />;
  const { debit: d, suggestions } = q.data;
  const open = (bills.data ?? []).filter((b) => b.pending > 0);

  return (
    <div className="card grid gap-10 p-6 lg:grid-cols-[1fr_1.6fr]">
      <div>
        <Mono>{d.transaction_id}</Mono>
        <p className="num mt-2 font-display text-[2rem] font-bold">{inr(d.debit_amount)} <span className="text-[14px] font-semibold text-fg-3">paid out</span></p>
        <div className="mt-4"><KV rows={[["Value date", fmtDate(d.transaction_date)], ["Bank", d.bank_name], ["UTR", d.utr, true], ["Narration", d.narration, true]]} /></div>
      </div>
      <div>
        {!who && <p className="mb-4 text-[14px] text-amber">Enter your name in the reviewer field above to link or undo payments.</p>}
        {d.links.map((p) => <Linked key={p.payment_id} p={p} />)}

        {d.unlinked > 0 && (
          <>
            <p className="mb-2 mt-1 text-[14px] font-semibold">{inr(d.unlinked)} not linked yet</p>
            {suggestions.map((s) => (
              <div key={s.bill_id} className="flex flex-wrap items-center justify-between gap-3 border-t border-line py-3">
                <div>
                  <p className="font-semibold">{s.vendor_name} <Mono>{s.bill_number}</Mono></p>
                  <p className="text-[13px] text-fg-3">{inr(s.pending)} pending · {s.reasons.join(", ")}</p>
                </div>
                <Button size="sm" variant="primary" disabled={!who} loading={link.isPending && link.variables === s.bill_id}
                  onClick={() => link.mutate(s.bill_id)}>Link {inr(s.would_link)}</Button>
              </div>
            ))}
            {!suggestions.length && <p className="border-t border-line py-3 text-[14px] text-fg-3">No unpaid bill shares a number, name or amount with this payment.</p>}

            <div className="flex flex-wrap gap-2.5 border-t border-line pt-4">
              <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Choose another bill" className={clsx(inputCls, "max-w-[420px] flex-1")}>
                <option value="">Choose another bill</option>
                {open.map((b) => <option key={b.bill_id} value={b.bill_id}>{b.vendor_name} · {b.bill_number} · {inr(b.pending)} pending</option>)}
              </select>
              <Button disabled={!who || !choice} onClick={() => link.mutate(choice)}>Link to bill</Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2.5">
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note, e.g. bank charge or salary"
                aria-label="Why this is not a vendor payment" className={clsx(inputCls, "max-w-[420px] flex-1")} />
              <Button disabled={!who || !note.trim()} loading={other.isPending} onClick={() => other.mutate()}>Not a vendor payment</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Linked({ p }: { p: VendorPayment }) {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const [note, setNote] = useState("");
  const undo = useMutation({
    mutationFn: () => api.unlinkPayment(p.payment_id, note.trim()),
    onSuccess: () => { toast.success("Link removed."); qc.invalidateQueries(); },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <div className="mb-4 border-t border-line pt-3">
      <p className="font-semibold">
        {inr(p.amount)} · {p.bill_id ? <>{p.vendor_name} <Mono>{p.bill_number}</Mono></> : "Not a vendor payment"}
      </p>
      <p className="text-[13px] text-fg-3">By {p.linked_by}{p.notes ? ` · ${p.notes}` : ""}</p>
      <div className="mt-2 flex flex-wrap gap-2.5">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason to undo" aria-label="Reason to undo"
          className={clsx(inputCls, "h-8 max-w-[320px] flex-1")} />
        <Button size="sm" variant="danger" disabled={!reviewer.trim() || !note.trim()} loading={undo.isPending} onClick={() => undo.mutate()}>Undo link</Button>
      </div>
    </div>
  );
}
