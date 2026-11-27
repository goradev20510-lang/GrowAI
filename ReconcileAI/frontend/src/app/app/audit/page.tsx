"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { api, type AuditRow } from "@/lib/api";
import { fmtTs } from "@/lib/format";
import { ErrorNote, Field, Mono, PageHead, Skeleton, inputCls } from "@/components/ui";

const ENTITIES = ["transaction", "allocation", "invoice", "review_case", "remittance", "batch", "system"];

export default function AuditPage() {
  const [q, setQ] = useState("");
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const dq = useDeferredValue(q);
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const logs = useQuery({ queryKey: ["audit", dq, entity, action], queryFn: () => api.audit({ q: dq, entity, action }) });
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <PageHead title="Activity" lede="Every automated and human action, newest first, with the evidence recorded at the time." />
      <div className="mb-8 grid gap-3 sm:grid-cols-[1.6fr_1fr_1fr]">
        <Field label="Search">
          <span className="relative block">
            <MagnifyingGlass className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-fg-4" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ID, action or detail" className={clsx(inputCls, "pl-10")} />
          </span>
        </Field>
        <Field label="Entity">
          <select value={entity} onChange={(e) => setEntity(e.target.value)} className={inputCls}>
            <option value="">All</option>{ENTITIES.map((e) => <option key={e} value={e}>{e.replace("_", " ")}</option>)}
          </select>
        </Field>
        <Field label="Action">
          <select value={action} onChange={(e) => setAction(e.target.value)} className={inputCls}>
            <option value="">All</option>{(meta.data?.audit_actions ?? []).map((a) => <option key={a} value={a}>{a.replaceAll("_", " ")}</option>)}
          </select>
        </Field>
      </div>
      {logs.error ? <ErrorNote error={logs.error} /> : !logs.data ? <Skeleton className="h-96" /> : !logs.data.length ? (
        <p className="card px-6 py-10 text-center text-fg-3">No entries match.</p>
      ) : (
        <>
          <p className="mb-4 text-[13px] text-fg-4">{logs.data.length} entries{logs.data.length === 500 ? " (limit 500)" : ""}. Select one to see the full record.</p>
          <ol className="relative border-l border-line pl-0">
            {logs.data.map((l) => <Entry key={l.log_id} l={l} open={open === l.log_id} toggle={() => setOpen(open === l.log_id ? null : l.log_id)} />)}
          </ol>
        </>
      )}
    </>
  );
}

function Entry({ l, open, toggle }: { l: AuditRow; open: boolean; toggle: () => void }) {
  const human = l.actor && !["system", "engine"].includes(l.actor.toLowerCase());
  const details = typeof l.details === "object" && l.details ? l.details : {};
  const short = Object.entries(details).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ").slice(0, 140);
  return (
    <li className="relative">
      <span className={clsx("absolute -left-[4.5px] top-[22px] size-2 rounded-full ring-4 ring-void", human ? "bg-ice" : "bg-fg-4")} aria-hidden />
      <button onClick={toggle} aria-expanded={open}
        className={clsx("grid w-full cursor-pointer gap-x-6 gap-y-1 rounded-r-lg py-4 pl-7 pr-5 text-left transition-colors md:grid-cols-[180px_1fr_auto]",
          open ? "bg-white/[0.04]" : "hover:bg-white/[0.02]")}>
        <span className="text-[13px] text-fg-3">{fmtTs(l.created_at)}</span>
        <span className="min-w-0">
          <span className="text-[14.5px] font-medium first-letter:uppercase">{l.action.replaceAll("_", " ")}</span>
          <span className="ml-2 text-[13px] text-fg-3">{l.entity_type.replace("_", " ")}</span> <Mono>{l.entity_id}</Mono>
          {short && <span className="mt-1 block truncate font-mono text-[12px] text-fg-4">{short}</span>}
        </span>
        <span className={clsx("text-[13px]", human ? "text-ice" : "text-fg-3")}>{l.actor}</span>
      </button>
      {open && (
        <div className="mb-3 ml-7 mr-5 rounded-lg border border-line bg-s1 p-5">
          <pre className="overflow-auto font-mono text-[12.5px] leading-relaxed text-fg-2">{typeof l.details === "string" ? l.details : JSON.stringify(l.details, null, 2)}</pre>
          <p className="mt-3 text-[12px] text-fg-4">Log ID {l.log_id}</p>
        </div>
      )}
    </li>
  );
}
