"use client";

import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { CaretDown, Check, X } from "@phosphor-icons/react";
import { api, type Case, type CaseDetail, type Invoice } from "@/lib/api";
import { fmtDate, fmtTs, inr, pct } from "@/lib/format";
import { CASE_STATUS, excLabel, invStatus } from "@/lib/vocab";
import { useReviewer } from "@/components/providers";
import { Button, ErrorNote, Field, KV, Mono, Notice, PageHead, Pills, SectionHead, Skeleton, Table, inputCls } from "@/components/ui";
import { EmptyLedger } from "@/components/app/EmptyLedger";

export default function ReviewPage() {
  const queue = useQuery({ queryKey: ["review"], queryFn: api.review });
  const [filter, setFilter] = useState("all");
  const [picked, setPicked] = useState<string | null>(null);

  const cases = useMemo(() => queue.data ?? [], [queue.data]);
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    cases.forEach((c) => m.set(c.exception_type, (m.get(c.exception_type) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [cases]);
  const shown = cases.filter((c) => filter === "all" || c.exception_type === filter);
  const current = shown.find((c) => c.case_id === picked) ?? shown[0];

  // J / K to move through the queue.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey) return;
      if (!shown.length || !current) return;
      const i = shown.findIndex((c) => c.case_id === current.case_id);
      if (e.key === "j") setPicked(shown[Math.min(shown.length - 1, i + 1)].case_id);
      if (e.key === "k") setPicked(shown[Math.max(0, i - 1)].case_id);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [shown, current]);

  const head = (
    <PageHead title="Review queue." lede="Credits the engine would not settle on its own. A named reviewer approves, rejects or reassigns each one, and every decision goes to the audit trail." />
  );
  if (queue.error) return <>{head}<ErrorNote error={queue.error} /></>;
  if (!queue.data) return <>{head}<Skeleton className="h-[520px]" /></>;

  return (
    <>
      {head}
      {cases.length === 0 ? (
        <NothingWaiting />
      ) : (
        <>
          <Pills value={filter} onChange={(v) => { setFilter(v); setPicked(null); }}
            options={[{ value: "all", label: "All", count: cases.length }, ...counts.map(([k, n]) => ({ value: k, label: excLabel(k), count: n }))]} />
          <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(300px,0.8fr)_1.6fr]">
            <div className="card lg:sticky lg:top-[136px]">
              <p className="flex items-center justify-between border-b border-line px-5 py-3.5 text-[12.5px] text-fg-3">
                <span>{shown.length} credits, largest first</span>
                <span className="hidden font-mono text-[11px] text-fg-4 lg:inline">J / K to move</span>
              </p>
              <ul className="max-h-[calc(100dvh-260px)] overflow-auto py-1.5" role="listbox" aria-label="Cases">
                {shown.map((c) => {
                  const active = c.case_id === current?.case_id;
                  return (
                    <li key={c.case_id} role="option" aria-selected={active}>
                      <button onClick={() => setPicked(c.case_id)}
                        className={clsx("relative flex w-full cursor-pointer items-center justify-between gap-4 px-5 py-3.5 text-left transition-colors duration-150",
                          active ? "bg-white/[0.06]" : "hover:bg-white/[0.03]")}>
                        <span className="min-w-0">
                          <span className="block font-mono text-[12.5px] text-fg">{c.transaction_id}</span>
                          <span className="mt-0.5 block truncate text-[13px] text-fg-3">{excLabel(c.exception_type)}</span>
                        </span>
                        <span className="num shrink-0 text-[14px]">{inr(c.amount)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
            <AnimatePresence mode="wait">
              {current && (
                <motion.div key={current.case_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.22, ease: [0.25, 1, 0.5, 1] }}>
                  <CaseView id={current.case_id} stale={current.stale ?? []} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </>
      )}
      <Resolved />
    </>
  );
}

function NothingWaiting() {
  const s = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  if (s.data && s.data.total_transactions === 0)
    return <EmptyLedger title="Nothing to review yet." body="Load the demo dataset and run reconciliation. Anything the engine can't settle confidently lands here." />;
  return <Notice tone="ice">Nothing waiting for review. Every credit is either settled or explained.</Notice>;
}

function CaseView({ id, stale }: { id: string; stale: string[] }) {
  const q = useQuery({ queryKey: ["case", id], queryFn: () => api.case(id) });
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-[640px]" />;
  const d = q.data;
  const { case: c, transaction: t, invoice: inv } = d;
  const credit = Number(t.credit_amount || 0);

  let gap: React.ReactNode = null;
  if (inv && d.proposed.length <= 1) {
    const out = Number(inv.outstanding_amount || 0);
    const taxable = Number(inv.taxable_amount || 0);
    const diff = Math.round((credit - out) * 100) / 100;
    if (Math.abs(diff) < 0.01) gap = <Notice tone="ice">The credit equals the {inr(out)} outstanding on {inv.invoice_id}.</Notice>;
    else if (diff < 0)
      gap = <Notice tone="amber">Short of the outstanding balance by <b className="text-fg">{inr(-diff)}</b>{taxable ? `, ${pct(-diff / taxable, 2)} of the taxable value (${inr(taxable)})` : ""}. Whether that is TDS, a part-payment or an error is the reviewer&apos;s call.</Notice>;
    else gap = <Notice tone="sea">More than the outstanding balance by <b className="text-fg">{inr(diff)}</b>.</Notice>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="card p-[clamp(22px,3vw,36px)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-mono text-[clamp(1.2rem,2vw,1.6rem)] tracking-[-0.02em]">{t.transaction_id}</h2>
            <p className="mt-2 text-[13px] text-fg-3">
              Case {c.case_id} · opened {fmtTs(c.created_at)}
              {stale.length > 0 && ` · ${stale.length} older open case${stale.length > 1 ? "s" : ""} for this credit will close with your decision`}
            </p>
          </div>
          <span className="rounded-full border border-amber/30 bg-amber/10 px-3 py-1 text-[13px] font-medium text-amber">{excLabel(c.exception_type)}</span>
        </div>

        <div className="mt-8 grid gap-8 md:grid-cols-2">
          <div>
            <p className="text-[13px] text-fg-3">Bank credit</p>
            <p className="num mt-1 font-display text-[2.2rem] tracking-[-0.04em]">{inr(credit)}</p>
            <div className="mt-4"><KV rows={[["Value date", fmtDate(t.transaction_date)], ["Bank", t.bank_name], ["UTR", t.utr, true], ["Narration", t.narration, true]]} /></div>
          </div>
          <div>
            {inv ? (
              <>
                <p className="text-[13px] text-fg-3">Outstanding on {inv.invoice_id}</p>
                <p className="num mt-1 font-display text-[2.2rem] tracking-[-0.04em]">{inr(inv.outstanding_amount)}</p>
                <div className="mt-4"><KV rows={[["Customer", inv.customer_name], ["Invoice date", fmtDate(inv.invoice_date)], ["Due", fmtDate(inv.due_date)],
                  ["Invoice total", inr(inv.total_amount)], ["Taxable value", inr(inv.taxable_amount)], ["Status", invStatus(inv.status).label]]} /></div>
              </>
            ) : (
              <>
                <p className="text-[13px] text-fg-3">Suggested invoice</p>
                <p className="mt-1 font-display text-[2.2rem] tracking-[-0.04em] text-fg-3">None</p>
                <p className="mt-4 text-[14px] text-fg-2">The engine could not point to an invoice. Check the remittance advice or ask the payer, then assign one below.</p>
              </>
            )}
          </div>
        </div>
        {gap && <div className="mt-8">{gap}</div>}
      </div>

      {d.proposed.length > 0 && (
        <div>
          <p className="mb-3 mt-2 text-[14px] font-medium">What approving will post</p>
          <Table rows={d.proposed} rowKey={(a) => a.allocation_id} cols={[
            { key: "i", head: "Invoice", cell: (a) => <Mono>{a.invoice_id}</Mono> },
            { key: "b", head: "Bank credit", num: true, cell: (a) => inr(a.bank_credit) },
            { key: "t", head: "TDS", num: true, cell: (a) => (a.tds ? `${inr(a.tds)}${a.tds_section ? ` · ${a.tds_section}` : ""}` : "—") },
            { key: "a", head: "Applied", num: true, cell: (a) => inr(a.applied) },
            { key: "s", head: "Match score", num: true, cell: (a) => <ScoreBar v={a.score} /> },
          ]} />
        </div>
      )}

      <div className="card p-7">
        <p className="text-[14px] font-medium">Why it&apos;s here</p>
        <p className="mt-2 max-w-[70ch] text-[14.5px] leading-relaxed text-fg-2">{c.exception_summary ?? "—"}</p>
        {c.suggested_action && <p className="mt-3 text-[13px] text-fg-3">Suggested next step: {c.suggested_action}</p>}
      </div>

      <Disclosure title={`Remittance advice · ${d.remittance ? "linked by UTR" : "none with this UTR"}`}>
        {d.remittance ? (
          <>
            <KV rows={[["Payer", d.remittance.customer_name], ["Invoices quoted", d.remittance.invoice_references.join(", ") || "—"],
              ["Amount paid", inr(d.remittance.payment_amount)],
              ["TDS stated", inr(d.remittance.tds_amount) + (d.remittance.tds_section ? ` under ${d.remittance.tds_section}` : "")],
              ["Payment date", fmtDate(d.remittance.payment_date)], ["UTR", d.remittance.utr, true]]} />
            {d.remittance.evidence_text.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-[12.5px] text-fg-3">Verbatim excerpt the figures were extracted from</p>
                {d.remittance.evidence_text.map((x, i) => (
                  <blockquote key={i} className="mb-2 rounded-xl border border-line bg-black/40 px-4 py-3 font-mono text-[12.5px] leading-relaxed text-fg-2">{x}</blockquote>
                ))}
              </div>
            )}
          </>
        ) : <p className="text-[14px] text-fg-3">No imported payment email quotes this UTR.</p>}
      </Disclosure>
      {d.proposed[0]?.decision_reason && (
        <Disclosure title="Engine explanation">
          <p className="whitespace-pre-line text-[14px] leading-relaxed text-fg-2">{d.proposed[0].decision_reason}</p>
        </Disclosure>
      )}

      <Decision d={d} />
    </div>
  );
}

function ScoreBar({ v }: { v: number }) {
  return (
    <span className="inline-flex items-center gap-2.5" title="Engine's matching score, not a probability.">
      <span className="h-1 w-16 overflow-hidden rounded-full bg-white/10"><span className="block h-full bg-ice" style={{ width: pct(v) }} /></span>
      <span className="num text-fg-2">{pct(v)}</span>
    </span>
  );
}

function Disclosure({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full cursor-pointer items-center justify-between px-7 py-5 text-left text-[14px] font-medium">
        {title}
        <CaretDown className={clsx("size-4 text-fg-3 transition-transform duration-300", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.25, 1, 0.5, 1] }} className="overflow-hidden">
            <div className="px-7 pb-7">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Decision({ d }: { d: CaseDetail }) {
  const qc = useQueryClient();
  const { reviewer } = useReviewer();
  const who = reviewer.trim();
  const c = d.case;
  const credit = Number(d.transaction.credit_amount || 0);
  const [note, setNote] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const statedTds = Number(d.remittance?.tds_amount || 0) || d.proposed.reduce((s, a) => s + a.tds, 0);
  const [tds, setTds] = useState(statedTds);
  const [section, setSection] = useState<string>(d.remittance?.tds_section ?? "");
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const noteRef = useRef<HTMLTextAreaElement>(null);

  const decide = useMutation({
    mutationFn: (action: string) => api.decide(c.case_id, {
      action, notes: note.trim(), invoice_ids: chosen, tds_amount: tds, tds_section: section || null,
    }),
    onSuccess: (res, action) => {
      const tid = c.transaction_id;
      const msg: Record<string, string> = {
        approve: `Approved. ${tid} applied to ${((res.invoices as string[]) ?? []).join(", ")}.`,
        reject: `Rejected. ${tid} is unmatched again and those invoices won't be proposed for it.`,
        dismiss: `${tid} marked as not a customer payment.`,
        dup_confirm: `${tid} confirmed as a duplicate.`,
        dup_release: `${tid} released and re-reconciled.`,
        assign: `${tid} applied to ${chosen.join(", ")}.`,
      };
      toast.success(msg[action] ?? "Saved.");
      qc.invalidateQueries();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const needNote = (action: string) => {
    if (action !== "approve" && action !== "dup_confirm" && !note.trim()) {
      toast.error("Add a note for the audit trail first. It's required for this decision.");
      noteRef.current?.focus();
      return true;
    }
    return false;
  };
  const run = (action: string) => { if (!needNote(action)) decide.mutate(action); };

  // A to approve.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select") || e.metaKey || e.ctrlKey) return;
      if (e.key === "a" && who && d.proposed.length && c.exception_type !== "possible_duplicate") run("approve");
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  const pending = decide.isPending ? decide.variables : null;
  const dup = c.exception_type === "possible_duplicate";
  const sections = Object.entries(meta.data?.tds_sections ?? {});

  return (
    <div className="card p-[clamp(22px,3vw,36px)]">
      <h3 className="text-[1.5rem]">Decision.</h3>
      {!who && <div className="mt-4"><Notice tone="amber">Enter your name in the reviewer field above. Every decision is recorded against it.</Notice></div>}
      <div className="mt-6">
        <Field label="Note for the audit trail" hint="Required for anything except approving.">
          <textarea ref={noteRef} value={note} onChange={(e) => setNote(e.target.value)} rows={3}
            placeholder="e.g. Payer confirmed TDS under 194J; Form 16A requested."
            className={clsx(inputCls, "h-auto resize-y py-3 leading-relaxed")} />
        </Field>
      </div>

      {dup ? (
        <div className="mt-6 flex flex-wrap gap-2.5">
          <Button variant="primary" disabled={!who} loading={pending === "dup_confirm"} onClick={() => run("dup_confirm")}>Confirm duplicate</Button>
          <Button disabled={!who} loading={pending === "dup_release"} onClick={() => run("dup_release")}>Not a duplicate, reconcile it</Button>
        </div>
      ) : (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-2.5">
            <Button variant="primary" disabled={!who || !d.proposed.length} loading={pending === "approve"} onClick={() => run("approve")}
              title={d.proposed.length ? "Shortcut: A" : "There is no proposed allocation on this case."}>
              <Check weight="bold" className="size-4" /> Approve
            </Button>
            <Button disabled={!who || !d.proposed.length} loading={pending === "reject"} onClick={() => run("reject")}>
              <X weight="bold" className="size-4" /> Reject
            </Button>
            <Button variant="quiet" disabled={!who} loading={pending === "dismiss"} onClick={() => run("dismiss")}
              title="Interest, refund or internal transfer. Excluded from receivables.">
              Not a customer payment
            </Button>
          </div>

          <div className="mt-10 border-t border-line pt-8">
            <p className="text-[14px] font-medium">Or apply it to other invoices</p>
            <p className="mt-1 text-[13px] text-fg-3">Each invoice&apos;s balance is cleared in the order you pick them; any excess stays on the last one.</p>
            <InvoicePicker credit={credit} chosen={chosen} setChosen={setChosen} />
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <Field label="TDS deducted by the customer (₹)" hint="Pre-filled from the remittance advice when it states one.">
                <input type="number" min={0} step={100} value={tds} onChange={(e) => setTds(Number(e.target.value) || 0)} className={clsx(inputCls, "num")} />
              </Field>
              <Field label="TDS section">
                <select value={section} onChange={(e) => setSection(e.target.value)} className={inputCls}>
                  <option value="">None</option>
                  {sections.map(([k, r]) => <option key={k} value={k}>{k} · {pct(r)}</option>)}
                </select>
              </Field>
            </div>
            <div className="mt-6 flex flex-wrap items-center gap-4">
              <Button disabled={!who || !chosen.length} loading={pending === "assign"}
                onClick={() => (tds > 0 && !section ? toast.error("Pick the TDS section the customer deducted under.") : run("assign"))}>
                Apply to selected invoices
              </Button>
              {chosen.length > 0 && (
                <span className="text-[13px] text-fg-3">
                  {inr(credit + tds)} will be applied: {inr(credit)} bank credit{tds ? ` + ${inr(tds)} TDS` : ""}.
                </span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function InvoicePicker({ credit, chosen, setChosen }: { credit: number; chosen: string[]; setChosen: (v: string[]) => void }) {
  const q = useQuery({ queryKey: ["openInvoices", credit], queryFn: () => api.openInvoices(credit) });
  const [search, setSearch] = useState("");
  const list = (q.data ?? []).filter((i: Invoice) =>
    !search || `${i.invoice_id} ${i.customer_name ?? ""}`.toLowerCase().includes(search.toLowerCase())).slice(0, 40);
  const toggle = (id: string) => setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-line">
      <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Type an invoice number or customer"
        className="h-11 w-full border-b border-line bg-transparent px-4 text-[14px] placeholder:text-fg-4 focus:outline-none" aria-label="Search invoices" />
      <ul className="max-h-56 overflow-auto">
        {list.map((i) => {
          const order = chosen.indexOf(i.invoice_id);
          return (
            <li key={i.invoice_id}>
              <button onClick={() => toggle(i.invoice_id)} aria-pressed={order >= 0}
                className={clsx("flex w-full cursor-pointer items-center gap-4 px-4 py-2.5 text-left text-[13.5px] transition-colors", order >= 0 ? "bg-ice/[0.08]" : "hover:bg-white/[0.03]")}>
                <span className={clsx("num grid size-5 shrink-0 place-items-center rounded-full border text-[11px]", order >= 0 ? "border-ice bg-ice text-black" : "border-line-3")}>
                  {order >= 0 ? order + 1 : ""}
                </span>
                <span className="font-mono text-[12.5px]">{i.invoice_id}</span>
                <span className="min-w-0 flex-1 truncate text-fg-3">{i.customer_name}</span>
                <span className="num">{inr(i.outstanding_amount)} due</span>
              </button>
            </li>
          );
        })}
        {!list.length && <li className="px-4 py-4 text-[13px] text-fg-3">No open invoices match.</li>}
      </ul>
    </div>
  );
}

function Resolved() {
  const q = useQuery({ queryKey: ["resolved"], queryFn: api.resolved });
  if (!q.data?.length) return null;
  return (
    <>
      <SectionHead title={`Resolved cases · ${q.data.length}`} />
      <Table<Case> rows={q.data} rowKey={(c) => c.case_id} max={480} cols={[
        { key: "d", head: "Decided", cell: (c) => <span className="text-fg-2">{fmtTs(c.reviewed_at)}</span> },
        { key: "t", head: "Transaction", cell: (c) => <Mono>{c.transaction_id}</Mono> },
        { key: "r", head: "Reason", cell: (c) => excLabel(c.exception_type), className: "max-md:hidden" },
        { key: "o", head: "Outcome", cell: (c) => CASE_STATUS[c.status] ?? c.status },
        { key: "w", head: "Reviewer", cell: (c) => c.reviewer ?? "—" },
        { key: "n", head: "Note", cell: (c) => <span className="line-clamp-1 max-w-[30ch] text-fg-3">{c.resolution_notes}</span>, className: "max-lg:hidden" },
      ]} />
    </>
  );
}
