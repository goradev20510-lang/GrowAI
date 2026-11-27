"use client";

import clsx from "clsx";
import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { Button, PageHead } from "@/components/ui";

const EXAMPLES = ["Which credits are still unmatched?", "Which invoices are part-paid?", "How much TDS have customers deducted?", "Summarise the open review cases"];

type Msg = { role: "user" | "assistant"; content: string; used_llm?: boolean; source?: string | null; rows?: unknown; error?: boolean };

export default function AskPage() {
  const [history, setHistory] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: api.ask,
    onSuccess: (r) => setHistory((h) => [...h, { role: "assistant", content: r.answer, used_llm: r.used_llm, source: r.source, rows: r.rows }]),
    onError: (e) => setHistory((h) => [...h, { role: "assistant", content: `The assistant is unavailable: ${(e as Error).message}`, error: true }]),
  });
  const send = (q: string) => {
    const text = q.trim();
    if (!text || ask.isPending) return;
    setHistory((h) => [...h, { role: "user", content: text }]);
    setInput("");
    ask.mutate(text);
  };
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, ask.isPending]);

  return (
    <div className="mx-auto max-w-[860px]">
      <PageHead title="Ask the data" lede="Each question is routed to a fixed database lookup; the model, when configured, only words the answer. Every reply shows the lookup and the rows it used." />
      {!history.length && (
        <div className="grid gap-2 sm:grid-cols-2">
          {EXAMPLES.map((e) => (
            <button key={e} onClick={() => send(e)}
              className="card cursor-pointer px-5 py-4 text-left text-[14.5px] text-fg-2 transition-colors hover:border-line-3 hover:text-fg">{e}</button>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-8">
        <AnimatePresence initial={false}>
          {history.map((m, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: [0.25, 1, 0.5, 1] }}
              className={clsx(m.role === "user" ? "self-end rounded-lg bg-white/[0.07] px-5 py-3 text-[15px]" : "self-stretch")}>
              {m.role === "user" ? m.content : <Answer m={m} />}
            </motion.div>
          ))}
        </AnimatePresence>
        {ask.isPending && <p className="animate-pulse text-[14px] text-fg-3">Looking it up…</p>}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="sticky bottom-6 mt-10 flex items-center gap-2 rounded-lg border border-line-2 bg-s2 p-1.5 pl-4 focus-within:border-ice/50">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about credits, invoices, TDS or review cases"
          aria-label="Question" className="h-11 flex-1 bg-transparent text-[15px] placeholder:text-fg-4 focus:outline-none" />
        <button type="submit" disabled={!input.trim() || ask.isPending} aria-label="Send"
          className="grid size-11 cursor-pointer place-items-center rounded-md bg-white text-hero transition-opacity disabled:opacity-30">
          <ArrowUp weight="bold" className="size-4" />
        </button>
      </form>
      {history.length > 0 && <div className="mt-4 text-center"><Button size="sm" variant="quiet" onClick={() => setHistory([])}>Clear conversation</Button></div>}
    </div>
  );
}

function Answer({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false);
  const rows = Array.isArray(m.rows) ? (m.rows as Record<string, unknown>[]) : null;
  const cols = rows?.length ? Object.keys(rows[0]) : [];
  return (
    <div className="border-l border-line-2 pl-6">
      <p className={clsx("whitespace-pre-line text-[1.05rem] leading-relaxed", m.error ? "text-brick" : "text-fg")}>{m.content}</p>
      {m.used_llm !== undefined && (
        <p className="mt-3 text-[12.5px] text-fg-4">{m.used_llm ? "Worded by the model from the data below." : "Computed from the data below. No model was used."}</p>
      )}
      {m.source && (
        <div className="mt-3">
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="cursor-pointer text-[13px] text-fg-2 underline decoration-line-3 hover:text-fg">
            Data used · <span className="font-mono">{m.source}</span> · {rows ? rows.length : 1} record{rows?.length === 1 ? "" : "s"}
          </button>
          {open && (
            <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-line">
              {rows && rows.length ? (
                <table className="w-full text-[12.5px]">
                  <thead className="sticky top-0 bg-s1"><tr>{cols.map((c) => <th key={c} className="border-b border-line px-3 py-2 text-left font-medium text-fg-3">{c}</th>)}</tr></thead>
                  <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-line last:border-0">{cols.map((c) => <td key={c} className="num px-3 py-2 text-fg-2">{String(r[c] ?? "—")}</td>)}</tr>)}</tbody>
                </table>
              ) : <pre className="p-4 font-mono text-[12px] text-fg-2">{JSON.stringify(m.rows, null, 2)}</pre>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
